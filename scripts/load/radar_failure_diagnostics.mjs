function safeText(value) {
  return String(value || '')
    .replace(/[\r\n\t]+/g, ' ')
    .trim()
    .slice(0, 128);
}

function headerValue(response, wanted) {
  const headers = response && response.headers ? response.headers : {};
  const match = Object.keys(headers).find(
    (name) => name.toLowerCase() === wanted.toLowerCase()
  );
  return match ? safeText(headers[match]) : '';
}

export function buildFailureDiagnostic(endpoint, response) {
  const status = Number(response && response.status) || 0;
  if (status === 200) return null;

  return {
    endpoint: safeText(endpoint),
    status,
    error_code: Number(response && response.error_code) || 0,
    cf_ray: headerValue(response, 'CF-Ray'),
    cf_cache: headerValue(response, 'CF-Cache-Status'),
    radar_cache: headerValue(response, 'X-Radar-Edge-Cache'),
  };
}
