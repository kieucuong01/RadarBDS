function safeText(value) {
  return String(value || '')
    .replace(/[\r\n\t]+/g, ' ')
    .trim()
    .slice(0, 128);
}

export function safeHeaderValue(response, wanted) {
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
    cf_ray: safeHeaderValue(response, 'CF-Ray'),
    cf_cache: safeHeaderValue(response, 'CF-Cache-Status'),
    cf_error_type: safeHeaderValue(response, 'CF-Error-Type'),
    cf_error_origin: safeHeaderValue(response, 'CF-Error-Origin'),
    radar_cache: safeHeaderValue(response, 'X-Radar-Edge-Cache'),
  };
}
