(function () {
  const merged = Object.assign({}, window.Api, window.ApiNew);
  window.Api = merged;
})();
