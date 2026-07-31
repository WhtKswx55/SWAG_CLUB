window.SwagAuth = (function () {
  var tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;

  function getInitData() {
    return tg && tg.initData ? tg.initData : "";
  }

  async function fetchStatus() {
    var initData = getInitData();
    if (!initData) {
      return { ok: false, level: 0, level_name: "Гость", has_access: false, offline: true };
    }
    try {
      var res = await fetch("/api/status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData: initData }),
      });
      var data = await res.json();
      return data;
    } catch (e) {
      return { ok: false, level: 0, level_name: "Гость", has_access: false, error: true };
    }
  }

  async function createInvoiceLink(months) {
    var initData = getInitData();
    if (!initData) {
      return { ok: false, message: "Открой приложение через Telegram, чтобы оформить подписку" };
    }
    try {
      var res = await fetch("/api/create-invoice-link", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData: initData, months: months || 1 }),
      });
      return await res.json();
    } catch (e) {
      return { ok: false, message: "Ошибка сети, попробуй ещё раз" };
    }
  }

  return {
    tg: tg,
    getInitData: getInitData,
    fetchStatus: fetchStatus,
    createInvoiceLink: createInvoiceLink,
  };
})();