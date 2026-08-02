import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath, pathToFileURL } from 'node:url';


const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const entryPath = path.join(repoRoot, 'scripts', 'load', 'radar_public_load.js');
const warnings = [];
const responses = [
  {
    status: 200,
    headers: {
      'X-Radar-Edge-Cache': 'HIT',
      'CF-Cache-Status': 'HIT',
    },
    body: '<html>Radar BDS</html>',
  },
  {
    status: 522,
    error_code: 1211,
    headers: { 'CF-Ray': 'probe-ray-HKG' },
    body: 'phone=0909000000&source_url=private',
  },
  {
    status: 200,
    headers: {
      'X-Radar-Edge-Cache': 'HIT',
      'CF-Cache-Status': 'HIT',
    },
    body: '{"listings":[]}',
  },
];

const context = vm.createContext({
  __ENV: {
    BASE_URL: 'https://radarbds.vn',
    DURATION: '1s',
    REQUIRE_CDN: '1',
    RUN_ID: 'diagnostic-contract',
    SCENARIO: 'default',
    VUS: '1',
  },
  __ITER: 0,
  __VU: 1,
  console: {
    log() {},
    warn(message) { warnings.push(String(message)); },
  },
});
const modules = new Map();

function synthetic(identifier, exports) {
  const module = new vm.SyntheticModule(
    Object.keys(exports),
    function setExports() {
      for (const [name, value] of Object.entries(exports)) this.setExport(name, value);
    },
    { context, identifier }
  );
  modules.set(identifier, module);
  return module;
}

async function loadModule(filePath) {
  const identifier = pathToFileURL(filePath).href;
  if (modules.has(identifier)) return modules.get(identifier);
  const module = new vm.SourceTextModule(fs.readFileSync(filePath, 'utf8'), {
    context,
    identifier,
  });
  modules.set(identifier, module);
  await module.link(async (specifier, referencingModule) => {
    if (specifier === 'k6/http') {
      return modules.get(specifier) || synthetic(specifier, {
        default: { batch() { return responses; } },
      });
    }
    if (specifier === 'k6') {
      return modules.get(specifier) || synthetic(specifier, {
        check() { return true; },
        fail(message) { throw new Error(message); },
        sleep() {},
      });
    }
    if (specifier === 'k6/metrics') {
      class Counter { add() {} }
      return modules.get(specifier) || synthetic(specifier, { Counter });
    }
    return loadModule(fileURLToPath(new URL(specifier, referencingModule.identifier)));
  });
  await module.evaluate();
  return module;
}

const entry = await loadModule(entryPath);
for (let attempt = 0; attempt < 5; attempt += 1) entry.namespace.default();
process.stdout.write(JSON.stringify(warnings));
