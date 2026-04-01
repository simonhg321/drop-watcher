// Drop Watcher — lightweight visitor tracking
// Sets anonymous cookie, logs pageviews + referrer
(function() {
  function getCookie(name) {
    var m = document.cookie.match('(^|;)\\s*' + name + '=([^;]*)');
    return m ? m[2] : null;
  }

  function setCookie(name, val, days) {
    var d = new Date();
    d.setTime(d.getTime() + days * 86400000);
    document.cookie = name + '=' + val + ';path=/;expires=' + d.toUTCString() + ';SameSite=Lax;Secure';
  }

  function uuid() {
    return 'xxxxxxxx-xxxx'.replace(/x/g, function() {
      return (Math.random() * 16 | 0).toString(16);
    });
  }

  var vid = getCookie('dw_vid');
  if (!vid) {
    vid = uuid();
    setCookie('dw_vid', vid, 365);
  }

  var data = {
    vid: vid,
    path: location.pathname,
    ref: document.referrer || '',
    ts: new Date().toISOString()
  };

  fetch('/api/pageview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  }).catch(function() {});
})();
