/* Shared client-side helpers (R-2-101/102): one amount parser used by
 * every amount field this product has — pay-amount, request-amount,
 * authorize-amount, split-amount and authorization-capture-amount-{id} —
 * so none of them can drift from the others. Parses in integer/string
 * space throughout; never `parseFloat(x) * 100`, which cannot represent
 * every minor-unit amount exactly (R-1-004).
 */
(function () {
  "use strict";

  function parseAmountToMinorUnits(input, minorUnits) {
    var s = String(input == null ? "" : input).trim();
    if (!/^\d+(\.\d+)?$/.test(s)) {
      return null;
    }
    var dot = s.indexOf(".");
    var whole = dot === -1 ? s : s.slice(0, dot);
    var frac = dot === -1 ? "" : s.slice(dot + 1);
    if (frac.length > minorUnits) {
      return null; // R-2-102: too many decimal places is rejected, never rounded
    }
    while (frac.length < minorUnits) {
      frac += "0";
    }
    var digits = (whole + frac).replace(/^0+(?=\d)/, "");
    return parseInt(digits, 10);
  }

  function formatAmount(amount, currency, minorUnits) {
    var s = String(Math.trunc(amount));
    if (minorUnits === 0) {
      return s + " " + currency;
    }
    while (s.length < minorUnits + 1) {
      s = "0" + s;
    }
    var whole = s.slice(0, s.length - minorUnits);
    var frac = s.slice(s.length - minorUnits);
    return whole + "." + frac + " " + currency;
  }

  function showError(el, message) {
    if (!el) {
      return;
    }
    el.textContent = message;
    el.hidden = false;
  }

  function hideError(el) {
    if (!el) {
      return;
    }
    el.textContent = "";
    el.hidden = true;
  }

  window.Pocketful = {
    parseAmountToMinorUnits: parseAmountToMinorUnits,
    formatAmount: formatAmount,
    showError: showError,
    hideError: hideError
  };
})();

/* The `/` screen's interactive layer (R-2-150..160): one fetch wrapper,
 * one idempotency-key policy and one out-of-order-response guard, used
 * by every write form on this page instead of each form inventing its
 * own — R-2-186 applies to the UI's own internals here just as much as
 * to the JSON/form split, so pay/request/authorize can't drift from
 * each other either.
 */
(function () {
  "use strict";

  var sessionEl = document.getElementById("pocketful-session");
  if (!sessionEl) {
    return; // not an authed page (or no session) — nothing to wire up
  }
  var SESSION = JSON.parse(sessionEl.textContent);

  function escHtml(s) {
    var div = document.createElement("div");
    div.textContent = s == null ? "" : String(s);
    return div.innerHTML;
  }

  function randomKey() {
    return "k-" + Date.now() + "-" + Math.random().toString(36).slice(2);
  }

  function authHeaders(extra) {
    var headers = {Authorization: "Bearer " + SESSION.token};
    for (var k in extra) {
      headers[k] = extra[k];
    }
    return headers;
  }

  function slotEl(prefix) {
    return document.querySelector('[data-testid="' + prefix + '-error-slot"]');
  }

  function clearSlot(prefix) {
    var slot = slotEl(prefix);
    if (slot) {
      slot.innerHTML = "";
    }
  }

  function showSlot(prefix, kind, message) {
    var slot = slotEl(prefix);
    if (!slot) {
      return;
    }
    slot.innerHTML = "";
    var el = document.createElement("p");
    el.setAttribute("data-testid", prefix + "-" + kind);
    el.setAttribute("data-state", kind === "uncertain" ? "uncertain" : "error");
    el.className = kind === "uncertain" ? "form-uncertain" : "form-error";
    el.textContent = message;
    slot.appendChild(el);
  }

  // ---- wallet + activity refresh, each with its own sequence guard so a
  // slow earlier response can never clobber a faster later one (R-2-154) ----

  var meSeq = 0, meApplied = 0;

  function refreshWallet() {
    var seq = ++meSeq;
    fetch("/me", {headers: authHeaders()})
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (seq < meApplied) {
          return; // a later refresh already applied; this one is stale
        }
        meApplied = seq;
        applyWallet(data);
      });
  }

  function setAmountEl(testid, amount, currency, minorUnits) {
    var el = document.querySelector('[data-testid="' + testid + '"]');
    if (!el) {
      return;
    }
    el.setAttribute("data-amount", String(amount));
    el.textContent = Pocketful.formatAmount(amount, currency, minorUnits);
  }

  function applyWallet(data) {
    setAmountEl("wallet-balance", data.total, data.currency, data.minor_units);
    setAmountEl("wallet-available", data.available, data.currency, data.minor_units);
    var heldEl = document.querySelector('[data-testid="wallet-held"]');
    if (data.held > 0) {
      if (!heldEl) {
        heldEl = document.createElement("p");
        heldEl.setAttribute("data-testid", "wallet-held");
        heldEl.className = "wallet-amount wallet-held";
        var refreshBtn = document.querySelector('[data-testid="wallet-refresh"]');
        if (refreshBtn) {
          refreshBtn.parentNode.insertBefore(heldEl, refreshBtn);
        }
      }
      setAmountEl("wallet-held", data.held, data.currency, data.minor_units);
    } else if (heldEl) {
      heldEl.parentNode.removeChild(heldEl);
    }
  }

  var activitySeq = 0, activityApplied = 0;

  function refreshActivity() {
    var seq = ++activitySeq;
    fetch("/activity?limit=50", {headers: authHeaders()})
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (seq < activityApplied) {
          return;
        }
        activityApplied = seq;
        renderActivity(data.payments);
      });
  }

  function renderActivityItem(p) {
    var amountText = escHtml(Pocketful.formatAmount(p.amount, p.currency, SESSION.minor_units));
    return (
      '<article data-testid="activity-item-' + escHtml(p.payment_id) + '" data-visibility="' +
      escHtml(p.visibility) + '" class="activity-item">' +
      '<p data-testid="activity-parties-' + escHtml(p.payment_id) + '" class="activity-parties">' +
      escHtml(p.from_handle || "?") + " → " + escHtml(p.to_handle || "?") + "</p>" +
      '<p data-testid="activity-amount-' + escHtml(p.payment_id) + '" class="activity-amount">' +
      amountText + "</p>" +
      '<p data-testid="activity-note-' + escHtml(p.payment_id) + '" class="activity-note">' +
      escHtml(p.note) + "</p></article>"
    );
  }

  function renderActivity(payments) {
    var host = document.querySelector('[data-testid="activity-host"]');
    if (!host) {
      return;
    }
    var mount = host.querySelector(".activity-mount") || host;
    if (!payments.length) {
      mount.innerHTML = '<p data-testid="empty-activity" class="empty-state">No activity yet.</p>';
      return;
    }
    mount.innerHTML = '<div data-testid="activity-list">' + payments.map(renderActivityItem).join("") + "</div>";
  }

  function refreshAll() {
    refreshWallet();
    refreshActivity();
  }

  var refreshButton = document.querySelector('[data-testid="wallet-refresh"]');
  if (refreshButton) {
    refreshButton.addEventListener("click", refreshAll);
  }

  // ---- the write forms: pay, request, authorize — one generic binder ----

  var FORMS = [
    {
      prefix: "pay", path: "/payments", fields: ["handle", "amount", "note", "visibility"], uncertain: true,
      buildBody: function (v) {
        return {to_handle: v.handle, amount: v.amount, note: v.note, visibility: v.visibility};
      }
    },
    {
      prefix: "request", path: "/requests", fields: ["handle", "amount", "note"], uncertain: false,
      buildBody: function (v) {
        return {payer_handle: v.handle, amount: v.amount, note: v.note};
      }
    },
    {
      prefix: "authorize", path: "/authorizations", fields: ["handle", "amount", "note", "visibility"],
      uncertain: false,
      buildBody: function (v) {
        return {to_handle: v.handle, amount: v.amount, note: v.note, visibility: v.visibility};
      }
    }
  ];

  function bindForm(cfg) {
    var form = document.querySelector('[data-testid="' + cfg.prefix + '-form"]');
    if (!form) {
      return;
    }
    var fieldEls = {};
    cfg.fields.forEach(function (f) {
      fieldEls[f] = document.querySelector('[data-testid="' + cfg.prefix + "-" + f + '"]');
    });
    // R-2-151/152: the key is stable across resubmits of an UNCHANGED
    // form (so a resubmit is an ordinary §7 replay) and only regenerates
    // when a field's value actually changes — never on every click.
    var key = randomKey();
    cfg.fields.forEach(function (f) {
      if (fieldEls[f]) {
        fieldEls[f].addEventListener("input", function () { key = randomKey(); });
      }
    });

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      clearSlot(cfg.prefix);
      var values = {};
      for (var f in fieldEls) {
        if (fieldEls[f]) {
          values[f] = fieldEls[f].value;
        }
      }
      var amountMinor = Pocketful.parseAmountToMinorUnits(values.amount, SESSION.minor_units);
      if (amountMinor === null) {
        form.dataset.state = "error";
        showSlot(cfg.prefix, "error", "Enter a valid amount.");
        return; // R-2-102: never sent
      }
      values.amount = amountMinor;

      form.dataset.state = "loading";
      fetch(cfg.path, {
        method: "POST",
        headers: authHeaders({"Idempotency-Key": key, "Content-Type": "application/json"}),
        body: JSON.stringify(cfg.buildBody(values))
      }).then(function (resp) {
        return resp.json().then(function (data) { return {status: resp.status, body: data}; });
      }).then(function (result) {
        if (result.status >= 200 && result.status < 300) {
          form.dataset.state = "idle";
          clearSlot(cfg.prefix);
          // R-2-150: form values are never cleared on success.
          refreshAll(); // R-2-153: reflects the action with no manual reload
        } else {
          form.dataset.state = "error";
          var message = (result.body && result.body.error && result.body.error.message) || "Something went wrong.";
          showSlot(cfg.prefix, "error", message);
        }
      }).catch(function () {
        // R-2-157/158: the browser never saw a response — this is NOT a
        // refusal, so it must never render as `-error`. The key and the
        // body are untouched, so the next click (still-unchanged fields)
        // is the ordinary same-key-same-body replay, moving money once.
        if (cfg.uncertain) {
          form.dataset.state = "uncertain";
          showSlot(cfg.prefix, "uncertain",
                    "We couldn't confirm this went through. It's safe to try again.");
        } else {
          form.dataset.state = "error";
          showSlot(cfg.prefix, "error", "Something went wrong. Please try again.");
        }
      });
    });
  }

  FORMS.forEach(bindForm);

  // ---- /requests: incoming/outgoing lists, pay/decline/cancel (R-2-133,
  // R-2-134, R-2-156) — same endpoint-object-via-fetch discipline as the
  // write forms above, just reached through a delegated click handler
  // since these buttons are rebuilt on every refresh. ----

  function renderRequestItem(r) {
    var isRequester = r.requester_id === SESSION.user_id;
    var actions = "";
    if (r.status === "pending") {
      if (r.payer_id === SESSION.user_id) {
        actions += '<button type="button" data-testid="request-pay-' + escHtml(r.request_id) +
          '" data-action="pay" data-id="' + escHtml(r.request_id) + '" class="btn btn-primary">Pay</button>';
        actions += '<button type="button" data-testid="request-decline-' + escHtml(r.request_id) +
          '" data-action="decline" data-id="' + escHtml(r.request_id) + '" class="btn btn-ghost">Decline</button>';
      }
      if (isRequester) {
        actions += '<button type="button" data-testid="request-cancel-' + escHtml(r.request_id) +
          '" data-action="cancel" data-id="' + escHtml(r.request_id) + '" class="btn btn-ghost">Cancel</button>';
      }
    }
    var counterpart = isRequester ? r.payer_handle : r.requester_handle;
    return '<article data-testid="request-item-' + escHtml(r.request_id) + '" data-status="' +
      escHtml(r.status) + '" class="list-item">' +
      '<p class="list-item-parties">' + escHtml(counterpart || "?") + "</p>" +
      '<p data-testid="request-amount-' + escHtml(r.request_id) + '" class="list-item-amount">' +
      escHtml(Pocketful.formatAmount(r.amount, r.currency, SESSION.minor_units)) + "</p>" +
      '<p class="list-item-note">' + escHtml(r.note) + "</p>" +
      '<div class="list-item-actions">' + actions + "</div></article>";
  }

  function refreshRequestsList() {
    var incomingEl = document.querySelector('[data-testid="incoming-list"]');
    var outgoingEl = document.querySelector('[data-testid="outgoing-list"]');
    if (!incomingEl && !outgoingEl) {
      return; // not on /requests
    }
    Promise.all([
      fetch("/requests?direction=incoming&limit=200", {headers: authHeaders()}).then(function (r) { return r.json(); }),
      fetch("/requests?direction=outgoing&limit=200", {headers: authHeaders()}).then(function (r) { return r.json(); })
    ]).then(function (results) {
      if (incomingEl) {
        incomingEl.innerHTML = results[0].requests.map(renderRequestItem).join("");
      }
      if (outgoingEl) {
        outgoingEl.innerHTML = results[1].requests.map(renderRequestItem).join("");
      }
    });
  }

  // ---- /authorizations: capture/void (R-2-137, R-2-138) ----

  function renderAuthorizationItem(a) {
    var isPayer = a.from_user_id === SESSION.user_id;
    var actions = "";
    if (a.status === "open") {
      if (a.to_user_id === SESSION.user_id) {
        var remaining = Pocketful.formatAmount(a.remaining_amount, a.currency, SESSION.minor_units).split(" ")[0];
        actions = '<label class="field capture-field"><span class="field-label">Capture amount</span>' +
          '<input type="text" data-testid="authorization-capture-amount-' + escHtml(a.authorization_id) +
          '" value="' + escHtml(remaining) + '"></label>' +
          '<button type="button" data-testid="authorization-capture-' + escHtml(a.authorization_id) +
          '" data-action="capture" data-id="' + escHtml(a.authorization_id) + '" class="btn btn-primary">Capture</button>';
      } else if (isPayer) {
        actions = '<button type="button" data-testid="authorization-void-' + escHtml(a.authorization_id) +
          '" data-action="void" data-id="' + escHtml(a.authorization_id) + '" class="btn btn-ghost">Void</button>';
      }
    }
    var counterpart = isPayer ? a.to_handle : a.from_handle;
    var capturedHtml = "";
    if (a.captured_amount > 0) {
      capturedHtml = '<p data-testid="authorization-captured-' + escHtml(a.authorization_id) +
        '" class="list-item-captured">' +
        escHtml(Pocketful.formatAmount(a.captured_amount, a.currency, SESSION.minor_units)) + "</p>";
    }
    return '<article data-testid="authorization-item-' + escHtml(a.authorization_id) + '" data-status="' +
      escHtml(a.status) + '" class="list-item">' +
      '<p class="list-item-parties">' + escHtml(counterpart || "?") + "</p>" +
      '<p data-testid="authorization-amount-' + escHtml(a.authorization_id) + '" class="list-item-amount">' +
      escHtml(Pocketful.formatAmount(a.amount, a.currency, SESSION.minor_units)) + "</p>" +
      capturedHtml +
      '<p data-testid="authorization-expires-' + escHtml(a.authorization_id) + '" class="list-item-expires">' +
      escHtml(a.expires_at) + "</p>" +
      '<p class="list-item-note">' + escHtml(a.note) + "</p>" +
      '<div class="list-item-actions">' + actions + "</div></article>";
  }

  function refreshAuthorizationsList() {
    var listEl = document.querySelector('[data-testid="authorization-list"]');
    if (!listEl) {
      return; // not on /authorizations
    }
    fetch("/authorizations?limit=200", {headers: authHeaders()})
      .then(function (r) { return r.json(); })
      .then(function (data) {
        listEl.innerHTML = data.authorizations.map(renderAuthorizationItem).join("");
      });
  }

  // ---- the delegated action handler: pay/decline/cancel/capture/void ----

  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-action]");
    if (!btn) {
      return;
    }
    var action = btn.getAttribute("data-action");
    var id = btn.getAttribute("data-id");
    var isRequestAction = action === "pay" || action === "decline" || action === "cancel";
    var isAuthAction = action === "capture" || action === "void";
    if (!isRequestAction && !isAuthAction) {
      return;
    }
    var slotPrefix = isRequestAction ? "request" : "authorization";
    var path = isRequestAction ? "/requests/" + id + "/" + action : "/authorizations/" + id + "/" + action;
    var body = {};
    var headers = authHeaders({"Content-Type": "application/json"});
    if (action === "pay") {
      headers["Idempotency-Key"] = randomKey();
    }
    if (action === "capture") {
      headers["Idempotency-Key"] = randomKey();
      var amountEl = document.querySelector('[data-testid="authorization-capture-amount-' + id + '"]');
      if (amountEl) {
        var parsed = Pocketful.parseAmountToMinorUnits(amountEl.value, SESSION.minor_units);
        if (parsed !== null) {
          body.amount = parsed;
        }
      }
    }
    fetch(path, {method: "POST", headers: headers, body: JSON.stringify(body)})
      .then(function (resp) {
        return resp.json().then(function (data) { return {status: resp.status, body: data}; });
      })
      .then(function (result) {
        clearSlot(slotPrefix);
        if (!(result.status >= 200 && result.status < 300)) {
          var message = (result.body && result.body.error && result.body.error.message) || "Something went wrong.";
          showSlot(slotPrefix, "error", message);
        }
        // R-2-156: the list always refreshes after an action, success or
        // not — a stale button (e.g. a request someone else just
        // cancelled) must disappear, not just sit there answering 409.
        refreshRequestsList();
        refreshAuthorizationsList();
        refreshWallet();
        refreshActivity();
      })
      .catch(function () {
        showSlot(slotPrefix, "error", "Something went wrong. Please try again.");
      });
  });

  // ---- /split: client-side preview using the exact §9 share rule,
  // before anything is posted (R-2-136) ----

  function computeShares(amount, n) {
    var base = Math.floor(amount / n);
    var rem = amount % n;
    var shares = [];
    for (var i = 0; i < n; i++) {
      shares.push(i < rem ? base + 1 : base);
    }
    return shares;
  }

  function bindSplitForm() {
    var form = document.querySelector('[data-testid="split-form"]');
    if (!form) {
      return;
    }
    var amountEl = document.querySelector('[data-testid="split-amount"]');
    var handlesEl = document.querySelector('[data-testid="split-handles"]');
    var noteEl = document.querySelector('[data-testid="split-note"]');
    var previewEl = document.querySelector('[data-testid="split-preview"]');
    var key = randomKey();

    function parsedHandles() {
      return handlesEl.value.split(",").map(function (h) { return h.trim(); }).filter(function (h) { return h; });
    }

    function updatePreview() {
      var handles = parsedHandles();
      var amountMinor = Pocketful.parseAmountToMinorUnits(amountEl.value, SESSION.minor_units);
      if (amountMinor === null || handles.length === 0) {
        previewEl.innerHTML = "";
        return;
      }
      var shares = computeShares(amountMinor, handles.length);
      previewEl.innerHTML = handles.map(function (h, i) {
        return '<p data-testid="split-share-' + escHtml(h) + '" class="split-share">' +
          escHtml(Pocketful.formatAmount(shares[i], SESSION.currency, SESSION.minor_units)) + "</p>";
      }).join("");
    }

    [amountEl, handlesEl].forEach(function (el) {
      el.addEventListener("input", function () {
        key = randomKey();
        updatePreview();
      });
    });
    if (noteEl) {
      noteEl.addEventListener("input", function () { key = randomKey(); });
    }

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      clearSlot("split");
      var handles = parsedHandles();
      var amountMinor = Pocketful.parseAmountToMinorUnits(amountEl.value, SESSION.minor_units);
      if (amountMinor === null || handles.length === 0) {
        form.dataset.state = "error";
        showSlot("split", "error", "Enter a valid amount and at least one participant.");
        return;
      }
      form.dataset.state = "loading";
      fetch("/splits", {
        method: "POST",
        headers: authHeaders({"Idempotency-Key": key, "Content-Type": "application/json"}),
        body: JSON.stringify({amount: amountMinor, note: noteEl ? noteEl.value : "", participant_handles: handles})
      }).then(function (resp) {
        return resp.json().then(function (data) { return {status: resp.status, body: data}; });
      }).then(function (result) {
        if (result.status >= 200 && result.status < 300) {
          form.dataset.state = "idle";
          clearSlot("split");
          refreshWallet();
          refreshActivity();
          refreshRequestsList();
        } else {
          form.dataset.state = "error";
          var message = (result.body && result.body.error && result.body.error.message) || "Something went wrong.";
          showSlot("split", "error", message);
        }
      }).catch(function () {
        form.dataset.state = "error";
        showSlot("split", "error", "Something went wrong. Please try again.");
      });
    });
  }

  bindSplitForm();
})();
