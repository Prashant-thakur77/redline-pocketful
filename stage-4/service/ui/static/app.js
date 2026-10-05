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

  var SLOT_CLASS = {uncertain: "form-uncertain", success: "form-success", error: "form-error"};

  function showSlot(prefix, kind, message) {
    var slot = slotEl(prefix);
    if (!slot) {
      return;
    }
    slot.innerHTML = "";
    var el = document.createElement("p");
    el.setAttribute("data-testid", prefix + "-" + kind);
    el.setAttribute("data-state", kind);
    el.className = SLOT_CLASS[kind] || "form-error";
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

  function relativeTime(createdAt) {
    var then = new Date(createdAt).getTime();
    var seconds = Math.max(0, Math.floor((Date.now() - then) / 1000));
    if (seconds < 60) { return "now"; }
    if (seconds < 3600) { return Math.floor(seconds / 60) + "m"; }
    if (seconds < 86400) { return Math.floor(seconds / 3600) + "h"; }
    return Math.floor(seconds / 86400) + "d";
  }

  function dayLabel(createdAt) {
    var then = new Date(createdAt);
    var now = new Date();
    var sameDay = then.toDateString() === now.toDateString();
    if (sameDay) { return "Today"; }
    var yesterday = new Date(now);
    yesterday.setDate(now.getDate() - 1);
    if (then.toDateString() === yesterday.toDateString()) { return "Yesterday"; }
    return then.toISOString().slice(0, 10);
  }

  // R-U-015: summary/avatar/direction are additional elements alongside
  // the existing activity-parties/activity-amount/activity-note testids,
  // which keep their exact current text (R-U-011) -- mirrors the
  // server-rendered markup in service/ui/home.py so a client refresh
  // after a write never regresses to the plainer pre-U2 layout.
  function renderActivityItem(p) {
    var amountText = escHtml(Pocketful.formatAmount(p.amount, p.currency, SESSION.minor_units));
    var isOutgoing = p.from_user_id === SESSION.user_id;
    var directionCls = isOutgoing ? "activity-direction-out" : "activity-direction-in";
    var directionSign = isOutgoing ? "−" : "+";
    var counterpartHandle = isOutgoing ? (p.to_handle || "?") : (p.from_handle || "?");
    var verb = isOutgoing ? "You paid " + escHtml(p.to_handle || "?") :
      (p.to_user_id === SESSION.user_id ? escHtml(p.from_handle || "?") + " paid you" :
        escHtml(p.from_handle || "?") + " paid " + escHtml(p.to_handle || "?"));
    var summary = verb + (p.note ? " · " + escHtml(p.note) : "") + " · " + relativeTime(p.created_at);
    return (
      '<article data-testid="activity-item-' + escHtml(p.payment_id) + '" data-visibility="' +
      escHtml(p.visibility) + '" class="activity-item">' +
      '<div class="activity-avatar" aria-hidden="true">' + escHtml(counterpartHandle.slice(0, 2).toUpperCase()) + '</div>' +
      '<div class="activity-body">' +
      '<p class="activity-summary">' + summary + '</p>' +
      '<p data-testid="activity-parties-' + escHtml(p.payment_id) + '" class="activity-parties">' +
      escHtml(p.from_handle || "?") + " → " + escHtml(p.to_handle || "?") + "</p>" +
      '<p data-testid="activity-note-' + escHtml(p.payment_id) + '" class="activity-note">' +
      escHtml(p.note) + "</p></div>" +
      '<p class="activity-amount-wrap"><span class="activity-direction ' + directionCls +
      '" aria-hidden="true">' + directionSign + '</span>' +
      '<span data-testid="activity-amount-' + escHtml(p.payment_id) + '" class="activity-amount">' +
      amountText + "</span></p></article>"
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
    var parts = [];
    var lastDay = null;
    payments.forEach(function (p) {
      var day = dayLabel(p.created_at);
      if (day !== lastDay) {
        parts.push('<p class="activity-day-header">' + escHtml(day) + '</p>');
        lastDay = day;
      }
      parts.push(renderActivityItem(p));
    });
    mount.innerHTML = '<div data-testid="activity-list">' + parts.join("") + "</div>";
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

  // R-U-014: a live, non-blocking review of what a submit would do.
  // Updates as the fields change; the submit button itself still performs
  // the write on a single click (R-2-151/157 fill the form and click
  // pay-submit exactly once) -- this is informational, not a gate.
  function updateReview(cfg, fieldEls) {
    var review = document.querySelector('[data-testid="' + cfg.prefix + '-review"]');
    if (!review) {
      return;
    }
    var handle = fieldEls.handle ? fieldEls.handle.value.trim() : "";
    var amountMinor = fieldEls.amount ?
      Pocketful.parseAmountToMinorUnits(fieldEls.amount.value, SESSION.minor_units) : null;
    if (!handle || amountMinor === null) {
      review.hidden = true;
      review.textContent = "";
      return;
    }
    var amountText = Pocketful.formatAmount(amountMinor, SESSION.currency, SESSION.minor_units);
    var verb = cfg.prefix === "request" ? "Request " + amountText + " from " : "Pay " + amountText + " to ";
    var note = fieldEls.note ? fieldEls.note.value.trim() : "";
    review.textContent = verb + handle + (note ? " · " + note : "");
    review.hidden = false;
  }

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
        fieldEls[f].addEventListener("input", function () {
          key = randomKey();
          updateReview(cfg, fieldEls);
        });
      }
    });
    updateReview(cfg, fieldEls);

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
          showSlot(cfg.prefix, "success", "Sent.");
          // R-2-150: form values are never cleared on success.
        } else {
          form.dataset.state = "error";
          var message = (result.body && result.body.error && result.body.error.message) || "Something went wrong.";
          showSlot(cfg.prefix, "error", message);
        }
        // R-2-153/155: refreshes after EVERY definitive outcome, not just
        // success — a refusal (e.g. another client spent the balance
        // first) means the wallet moved too, and `-error` showing while
        // the numbers stay frozen at their pre-attempt values is exactly
        // adversary's BREACH. No manual reload either way.
        refreshAll();
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
        // The write may have committed even though the response was
        // lost — refresh so the numbers reflect reality either way.
        refreshAll();
      });
    });
  }

  FORMS.forEach(bindForm);

  // ---- R-U-012: the Pay/Request primary-action toggle. Both panels stay
  // rendered at all times (R-U-005); this only swaps which one carries the
  // "primary" emphasis via the wrapper's data-active attribute. ----
  (function bindPrimaryToggle() {
    var wrap = document.querySelector(".primary-action");
    if (!wrap) {
      return;
    }
    var buttons = wrap.querySelectorAll(".toggle-btn");
    buttons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        var target = btn.getAttribute("data-target");
        wrap.setAttribute("data-active", target);
        buttons.forEach(function (b) {
          var active = b === btn;
          b.classList.toggle("toggle-btn-active", active);
          b.setAttribute("aria-selected", active ? "true" : "false");
        });
        var payPanel = wrap.querySelector('[data-panel="pay"]');
        var requestPanel = wrap.querySelector('[data-panel="request"]');
        if (payPanel && requestPanel) {
          payPanel.classList.toggle("primary-panel", target === "pay");
          payPanel.classList.toggle("secondary-panel", target !== "pay");
          requestPanel.classList.toggle("primary-panel", target === "request");
          requestPanel.classList.toggle("secondary-panel", target !== "request");
        }
      });
    });
  })();

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
      // R-2-051: an OMITTED amount defaults to the full remaining amount —
      // a blank field is that, intentionally. A non-blank field that
      // fails to parse is not an omission, it's a mistake, and must
      // refuse to submit with a visible error (R-2-186: the same
      // never-silently-send-garbage discipline every other amount field
      // in bindForm already has) rather than silently falling through to
      // the same default and capturing far more than was typed.
      if (amountEl && amountEl.value.trim() !== "") {
        var parsed = Pocketful.parseAmountToMinorUnits(amountEl.value, SESSION.minor_units);
        if (parsed === null) {
          showSlot(slotPrefix, "error", "Enter a valid amount.");
          return;
        }
        body.amount = parsed;
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
    var chipsEl = document.querySelector('[data-testid="split-chips"]');
    var key = randomKey();

    function parsedHandles() {
      return handlesEl.value.split(",").map(function (h) { return h.trim(); }).filter(function (h) { return h; });
    }

    // R-U-018: removable chips are an ADDITIONAL affordance layered over
    // `split-handles`, which stays a plain fillable comma-separated text
    // input (R-U-005) -- removing a chip just rewrites that input's value
    // and dispatches "input" so the existing preview/key logic reacts to
    // it exactly as if the user had edited the text themselves.
    function renderChips() {
      if (!chipsEl) {
        return;
      }
      var handles = parsedHandles();
      chipsEl.innerHTML = handles.map(function (h, i) {
        return '<span class="split-chip">' + escHtml(h) +
          '<button type="button" class="split-chip-remove" data-index="' + i +
          '" aria-label="Remove ' + escHtml(h) + '">&times;</button></span>';
      }).join("");
    }

    if (chipsEl) {
      chipsEl.addEventListener("click", function (e) {
        var btn = e.target.closest(".split-chip-remove");
        if (!btn) {
          return;
        }
        var index = parseInt(btn.getAttribute("data-index"), 10);
        var handles = parsedHandles();
        handles.splice(index, 1);
        handlesEl.value = handles.join(", ");
        handlesEl.dispatchEvent(new Event("input", {bubbles: true}));
      });
    }

    function updatePreview() {
      renderChips();
      var handles = parsedHandles();
      var amountMinor = Pocketful.parseAmountToMinorUnits(amountEl.value, SESSION.minor_units);
      if (amountMinor === null || handles.length === 0) {
        previewEl.innerHTML = "";
        previewEl.dataset.state = "empty";
        return;
      }
      var shares = computeShares(amountMinor, handles.length);
      previewEl.innerHTML = handles.map(function (h, i) {
        return '<p data-testid="split-share-' + escHtml(h) + '" class="split-share">' +
          escHtml(Pocketful.formatAmount(shares[i], SESSION.currency, SESSION.minor_units)) + "</p>";
      }).join("");
      previewEl.removeAttribute("data-state");
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
        } else {
          form.dataset.state = "error";
          var message = (result.body && result.body.error && result.body.error.message) || "Something went wrong.";
          showSlot("split", "error", message);
        }
        refreshWallet();
        refreshActivity();
        refreshRequestsList();
      }).catch(function () {
        form.dataset.state = "error";
        showSlot("split", "error", "Something went wrong. Please try again.");
        refreshWallet();
        refreshActivity();
        refreshRequestsList();
      });
    });
  }

  bindSplitForm();

  // ---- /statement (R-U-030..033): date-only inputs converted to the
  // RFC 3339 instants the API requires (R-3-030) -- a bare date is
  // 422_validation_failed, so every conversion happens here, once, before
  // any fetch. as_of/known_at are independent axes (R-U-032): both are
  // sent whenever present, neither derived from the other. ----
  (function bindStatementScreen() {
    var screen = document.getElementById("statement-screen");
    if (!screen) {
      return;
    }
    var fromEl = document.querySelector('[data-testid="statement-from"]');
    var toEl = document.querySelector('[data-testid="statement-to"]');
    var asOfEl = document.querySelector('[data-testid="statement-as-of"]');
    var knownAtEl = document.querySelector('[data-testid="statement-known-at"]');
    var applyBtn = document.querySelector('[data-testid="statement-apply"]');
    var prevBtn = document.querySelector('[data-testid="statement-prev"]');
    var nextBtn = document.querySelector('[data-testid="statement-next"]');
    var errorEl = document.querySelector('[data-testid="statement-error"]');
    var loadingEl = document.querySelector('[data-testid="statement-loading"]');
    var listEl = document.querySelector('[data-testid="statement-list"]');
    var noteEl = document.querySelector('[data-testid="statement-snapshot-note"]');
    var openingEl = document.querySelector('[data-testid="statement-opening-balance"]');
    var closingEl = document.querySelector('[data-testid="statement-closing-balance"]');
    var asOfBalanceEl = document.querySelector('[data-testid="as-of-balance"]');

    function dayStart(dateStr) { return dateStr + "T00:00:00+00:00"; }
    function dayEnd(dateStr) { return dateStr + "T23:59:59+00:00"; }
    function nextDayStart(dateStr) {
      var d = new Date(dateStr + "T00:00:00Z");
      d.setUTCDate(d.getUTCDate() + 1);
      return dayStart(d.toISOString().slice(0, 10));
    }

    function currency() { return screen.getAttribute("data-currency"); }
    function minorUnits() { return parseInt(screen.getAttribute("data-minor-units"), 10); }

    function showError(message) {
      errorEl.hidden = false;
      errorEl.textContent = message;
    }
    function clearError() {
      errorEl.hidden = true;
      errorEl.textContent = "";
    }
    function setLoading(on) {
      loadingEl.hidden = !on;
    }

    function renderEntry(entry) {
      var amt = Pocketful.formatAmount(entry.amount, currency(), minorUnits());
      var bal = Pocketful.formatAmount(entry.balance_after, currency(), minorUnits());
      return '<article data-testid="statement-entry-' + escHtml(entry.payment_id) + '" class="list-item">' +
        '<p class="list-item-parties">' + escHtml(entry.effective_at) + '</p>' +
        '<p data-testid="statement-entry-amount-' + escHtml(entry.payment_id) + '" class="list-item-amount">' +
        escHtml(amt) + '</p>' +
        '<p data-testid="statement-entry-balance-' + escHtml(entry.payment_id) + '" class="list-item-amount">' +
        escHtml(bal) + '</p>' +
        '<p data-testid="statement-entry-revision-' + escHtml(entry.payment_id) + '" class="list-item-note">rev ' +
        entry.revision + '</p></article>';
    }

    function renderStatement(data, fromSnapshot) {
      screen.setAttribute("data-snapshot", data.snapshot);
      if (data.entries.length) {
        listEl.innerHTML = data.entries.map(renderEntry).join("");
      } else {
        listEl.innerHTML = '<p data-testid="empty-statement" class="empty-state">No entries in this window.</p>';
      }
      openingEl.textContent = Pocketful.formatAmount(data.opening_balance, currency(), minorUnits());
      closingEl.textContent = Pocketful.formatAmount(data.closing_balance, currency(), minorUnits());
      if (fromSnapshot) {
        noteEl.hidden = false;
        noteEl.textContent = "Viewing a frozen snapshot (" + data.snapshot + ") taken earlier in this session.";
      } else {
        noteEl.hidden = true;
      }
    }

    function fetchStatement(params, fromSnapshot) {
      setLoading(true);
      clearError();
      var qs = Object.keys(params).map(function (k) {
        return encodeURIComponent(k) + "=" + encodeURIComponent(params[k]);
      }).join("&");
      return fetch("/statement?" + qs, {headers: authHeaders()})
        .then(function (r) { return r.json().then(function (body) { return {status: r.status, body: body}; }); })
        .then(function (result) {
          setLoading(false);
          if (result.status >= 200 && result.status < 300) {
            renderStatement(result.body, fromSnapshot);
          } else {
            var message = (result.body.error && result.body.error.message) || "Something went wrong.";
            showError(message);
          }
        })
        .catch(function () {
          setLoading(false);
          showError("Something went wrong. Please try again.");
        });
    }

    function applyWindow() {
      var params = {limit: 50, offset: 0};
      if (fromEl.value) { params.from = dayStart(fromEl.value); }
      if (toEl.value) { params.to = nextDayStart(toEl.value); }
      if (knownAtEl.value) { params.known_at = dayEnd(knownAtEl.value); }
      screen.setAttribute("data-offset", "0");
      fetchStatement(params, false);

      if (asOfEl.value) {
        var meParams = {as_of: dayEnd(asOfEl.value)};
        if (knownAtEl.value) { meParams.known_at = dayEnd(knownAtEl.value); }
        var qs = Object.keys(meParams).map(function (k) {
          return encodeURIComponent(k) + "=" + encodeURIComponent(meParams[k]);
        }).join("&");
        fetch("/me?" + qs, {headers: authHeaders()})
          .then(function (r) { return r.json(); })
          .then(function (data) {
            asOfBalanceEl.textContent = Pocketful.formatAmount(data.total, data.currency, data.minor_units);
          });
      } else {
        asOfBalanceEl.textContent = "";
      }
    }

    function page(delta) {
      var offset = Math.max(0, parseInt(screen.getAttribute("data-offset"), 10) + delta);
      screen.setAttribute("data-offset", String(offset));
      fetchStatement({snapshot: screen.getAttribute("data-snapshot"), limit: 50, offset: offset}, true);
    }

    applyBtn.addEventListener("click", applyWindow);
    prevBtn.addEventListener("click", function () { page(-50); });
    nextBtn.addEventListener("click", function () { page(50); });
  })();

  // ---- payment detail: refund + correct (R-U-036..038). Both reuse the
  // SAME three-outcome pattern as the pay form (success / refused /
  // uncertain, R-2-157) -- a lost response is retried with the identical
  // key and body, never shown as a refusal. ----
  (function bindPaymentDetailActions() {
    var detailSection = document.querySelector('[data-payment-id]');
    if (!detailSection) {
      return;
    }
    var paymentId = detailSection.getAttribute("data-payment-id");
    var currency = detailSection.getAttribute("data-currency");
    var minorUnits = parseInt(detailSection.getAttribute("data-minor-units"), 10);

    function showActionSlot(prefix, kind, message) {
      ["error", "uncertain"].forEach(function (k) {
        var el = document.querySelector('[data-testid="' + prefix + '-' + k + '"]');
        if (el) { el.hidden = true; el.textContent = ""; }
      });
      var target = document.querySelector('[data-testid="' + prefix + '-' + kind + '"]');
      if (target) { target.hidden = false; target.textContent = message; }
    }

    function clearActionSlots(prefix) {
      ["error", "uncertain"].forEach(function (k) {
        var el = document.querySelector('[data-testid="' + prefix + '-' + k + '"]');
        if (el) { el.hidden = true; el.textContent = ""; }
      });
    }

    function submitWrite(prefix, path, key, body) {
      clearActionSlots(prefix);
      return fetch(path, {
        method: "POST",
        headers: authHeaders({"Idempotency-Key": key, "Content-Type": "application/json"}),
        body: JSON.stringify(body)
      }).then(function (resp) {
        return resp.json().then(function (data) { return {status: resp.status, body: data}; });
      }).then(function (result) {
        if (result.status >= 200 && result.status < 300) {
          showActionSlot(prefix, "error", ""); // clears; success has no dedicated slot beyond a reload
          clearActionSlots(prefix);
          location.reload();
        } else {
          // R-U-038: the API's own error text, shown plainly, never
          // relabelled -- refund_exceeds_payment, linked_payment_immutable,
          // insufficient_funds, historical_overdraft, stale_revision all
          // land here verbatim.
          var message = (result.body.error && result.body.error.message) || "Something went wrong.";
          showActionSlot(prefix, "error", message);
        }
      }).catch(function () {
        // R-2-157/R-U-038: the response was lost, not refused -- never
        // shown as `-error`. Retrying with the SAME key/body is safe.
        showActionSlot(prefix, "uncertain",
                        "We couldn't confirm this went through. It's safe to try again.");
      });
    }

    var refundForm = document.querySelector('[data-testid="refund-form"]');
    if (refundForm) {
      var refundAmountEl = document.querySelector('[data-testid="refund-amount"]');
      var refundReviewEl = document.querySelector('[data-testid="refund-review"]');
      // R-2-151/152 (R-U-042's actual rule, per the planner's amendment):
      // stable across resubmits of an UNCHANGED form, regenerated only
      // when a field's value actually changes -- the exact policy
      // bindForm already uses for pay/request/authorize, not a content
      // hash. No crypto.subtle, no fallback branch.
      var refundKey = randomKey();
      function updateRefundReview() {
        var amt = Pocketful.parseAmountToMinorUnits(refundAmountEl.value, minorUnits);
        if (amt === null) {
          refundReviewEl.hidden = true;
          return;
        }
        refundReviewEl.hidden = false;
        refundReviewEl.textContent = "Refund " + Pocketful.formatAmount(amt, currency, minorUnits);
      }
      refundAmountEl.addEventListener("input", function () {
        refundKey = randomKey();
        updateRefundReview();
      });
      updateRefundReview();
      document.querySelector('[data-testid="refund-submit"]').addEventListener("click", function () {
        var amt = Pocketful.parseAmountToMinorUnits(refundAmountEl.value, minorUnits);
        if (amt === null) {
          showActionSlot("refund", "error", "Enter a valid amount.");
          return;
        }
        submitWrite("refund", "/payments/" + paymentId + "/refunds", refundKey, {amount: amt});
      });
    }

    var correctForm = document.querySelector('[data-testid="correct-form"]');
    if (correctForm) {
      var correctAmountEl = document.querySelector('[data-testid="correct-amount"]');
      var correctReasonEl = document.querySelector('[data-testid="correct-reason"]');
      var correctEffectiveEl = document.querySelector('[data-testid="correct-effective"]');
      var correctExpectedEl = document.querySelector('[data-testid="correct-expected-revision"]');
      var correctReviewEl = document.querySelector('[data-testid="correct-review"]');

      function effectiveInstant() {
        if (correctEffectiveEl.value) {
          return new Date(correctEffectiveEl.value).toISOString();
        }
        return new Date().toISOString();
      }

      // Same stable-until-changed policy as the refund form above.
      var correctKey = randomKey();
      function regenerateCorrectKey() { correctKey = randomKey(); }

      function updateCorrectReview() {
        var amt = Pocketful.parseAmountToMinorUnits(correctAmountEl.value, minorUnits);
        if (amt === null) {
          correctReviewEl.hidden = true;
          return;
        }
        correctReviewEl.hidden = false;
        correctReviewEl.textContent = "Correct to " + Pocketful.formatAmount(amt, currency, minorUnits) +
          (correctReasonEl.value ? " · " + correctReasonEl.value : "");
      }
      correctAmountEl.addEventListener("input", function () { regenerateCorrectKey(); updateCorrectReview(); });
      correctReasonEl.addEventListener("input", function () { regenerateCorrectKey(); updateCorrectReview(); });
      correctEffectiveEl.addEventListener("input", regenerateCorrectKey);
      updateCorrectReview();

      document.querySelector('[data-testid="correct-submit"]').addEventListener("click", function () {
        var amt = Pocketful.parseAmountToMinorUnits(correctAmountEl.value, minorUnits);
        if (amt === null) {
          showActionSlot("correct", "error", "Enter a valid amount.");
          return;
        }
        if (!correctReasonEl.value) {
          showActionSlot("correct", "error", "Enter a reason.");
          return;
        }
        var effectiveAt = effectiveInstant();
        var expectedRevision = parseInt(correctExpectedEl.value, 10);
        var reason = correctReasonEl.value;
        submitWrite("correct", "/payments/" + paymentId + "/corrections", correctKey,
          {expected_revision: expectedRevision, amount: amt, effective_at: effectiveAt, reason: reason});
      });
    }
  })();

  // ---- operator batch corrections (R-U-039). The table is assembled
  // entirely client-side (no "pending corrections" read endpoint exists
  // to populate it from, R-U-001) and submitted as one
  // POST /correction-batches call. ----
  (function bindBatchScreen() {
    var screen = document.getElementById("batch-screen");
    if (!screen) {
      return;
    }
    var tbody = document.querySelector('[data-testid="batch-tbody"]');
    var emptyEl = document.querySelector('[data-testid="empty-batch"]');
    var previewEl = document.querySelector('[data-testid="batch-preview"]');
    var maxRows = parseInt(screen.getAttribute("data-max-rows"), 10);
    var rowCount = 0;
    // R-2-151/152: stable while the table is UNCHANGED, regenerated on
    // any row edit, add or remove -- a batch is one atomic write, so a
    // stale key across an edited table would replay the wrong body.
    var batchKey = randomKey();
    function regenerateBatchKey() { batchKey = randomKey(); }

    function rowHtml(index) {
      return '<tr data-testid="batch-row-' + index + '">' +
        '<td><input type="text" data-testid="batch-payment-id-' + index + '"></td>' +
        '<td><input type="text" data-testid="batch-amount-' + index + '"></td>' +
        '<td><input type="text" data-testid="batch-reason-' + index + '"></td>' +
        '<td><input type="text" data-testid="batch-expected-revision-' + index + '" value="1"></td>' +
        '<td><input type="datetime-local" data-testid="batch-effective-' + index + '"></td>' +
        '<td><button type="button" data-testid="batch-remove-' + index +
        '" data-index="' + index + '" class="btn btn-ghost">Remove</button></td></tr>';
    }

    function updateEmptyState() {
      emptyEl.hidden = tbody.children.length > 0;
    }

    function addRow() {
      if (rowCount >= maxRows) {
        return;
      }
      var index = rowCount++;
      tbody.insertAdjacentHTML("beforeend", rowHtml(index));
      regenerateBatchKey();
      updateEmptyState();
      updatePreview();
      tbody.querySelectorAll("input").forEach(function (el) {
        el.addEventListener("input", function () { regenerateBatchKey(); updatePreview(); });
      });
    }

    function collectRows() {
      var rows = [];
      tbody.querySelectorAll("tr").forEach(function (tr) {
        var paymentIdEl = tr.querySelector('[data-testid^="batch-payment-id-"]');
        var amountEl = tr.querySelector('[data-testid^="batch-amount-"]');
        var reasonEl = tr.querySelector('[data-testid^="batch-reason-"]');
        var expectedEl = tr.querySelector('[data-testid^="batch-expected-revision-"]');
        var effectiveEl = tr.querySelector('[data-testid^="batch-effective-"]');
        if (!paymentIdEl.value) {
          return;
        }
        var amt = Pocketful.parseAmountToMinorUnits(amountEl.value, SESSION.minor_units);
        rows.push({
          payment_id: paymentIdEl.value,
          amount: amt,
          reason: reasonEl.value,
          expected_revision: parseInt(expectedEl.value, 10),
          effective_at: effectiveEl.value ? new Date(effectiveEl.value).toISOString() : new Date().toISOString()
        });
      });
      return rows;
    }

    function updatePreview() {
      var rows = collectRows();
      if (!rows.length) {
        previewEl.hidden = true;
        return;
      }
      previewEl.hidden = false;
      previewEl.textContent = rows.length + " correction(s) queued: " +
        rows.map(function (r) { return r.payment_id; }).join(", ");
    }

    document.querySelector('[data-testid="batch-add"]').addEventListener("click", addRow);

    tbody.addEventListener("click", function (e) {
      var btn = e.target.closest('[data-testid^="batch-remove-"]');
      if (!btn) {
        return;
      }
      btn.closest("tr").remove();
      regenerateBatchKey();
      updateEmptyState();
      updatePreview();
    });

    function showBatchSlot(kind, message) {
      ["result", "error", "uncertain"].forEach(function (k) {
        var el = document.querySelector('[data-testid="batch-' + k + '"]');
        if (el) { el.hidden = true; el.textContent = ""; }
      });
      var target = document.querySelector('[data-testid="batch-' + kind + '"]');
      if (target) { target.hidden = false; target.textContent = message; }
    }

    document.querySelector('[data-testid="batch-submit"]').addEventListener("click", function () {
      var rows = collectRows();
      if (!rows.length) {
        showBatchSlot("error", "Add at least one row.");
        return;
      }
      if (rows.some(function (r) { return r.amount === null; })) {
        showBatchSlot("error", "Every row needs a valid amount.");
        return;
      }
      fetch("/correction-batches", {
        method: "POST",
        headers: authHeaders({"Idempotency-Key": batchKey, "Content-Type": "application/json"}),
        body: JSON.stringify({corrections: rows})
      }).then(function (resp) {
        return resp.json().then(function (data) { return {status: resp.status, body: data}; });
      }).then(function (result) {
        // R-U-039: all-or-nothing -- POST /correction-batches never
        // partially applies, so a single result/error covers the whole
        // batch, never a per-row verdict.
        if (result.status >= 200 && result.status < 300) {
          showBatchSlot("result", "Batch committed: " + result.body.revisions.length + " correction(s).");
        } else {
          var message = (result.body.error && result.body.error.message) || "Something went wrong.";
          showBatchSlot("error", message);
        }
      }).catch(function () {
        showBatchSlot("uncertain", "We couldn't confirm this went through. It's safe to try again.");
      });
    });
  })();
})();
