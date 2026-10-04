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
