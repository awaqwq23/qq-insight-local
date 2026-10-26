const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const asar = require('@electron/asar');

const root = path.resolve(__dirname, '..');
const archive = path.join(root, 'release/win-unpacked/resources/app.asar');
const sourcePackage = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
const packedPackage = JSON.parse(asar.extractFile(archive, 'package.json').toString('utf8'));
// electron-builder intentionally strips development scripts and build configuration.
for (const key of ['name', 'version', 'main']) assert.equal(packedPackage[key], sourcePackage[key]);
function walk(relative) {
  for (const entry of fs.readdirSync(path.join(root, relative), { withFileTypes: true })) {
    const next = relative + '/' + entry.name;
    if (entry.isDirectory()) walk(next);
    else assert.deepEqual(asar.extractFile(archive, path.normalize(next)), fs.readFileSync(path.join(root, next)), next);
  }
}
walk('src/desktop');
assert.equal(packedPackage.license,'MIT');
const legal=path.join(root,'release/win-unpacked/resources/legal'),prepared=path.join(root,'build/legal');
const noticeManifest=JSON.parse(fs.readFileSync(path.join(root,'licenses/manifest.json'),'utf8'));
const licenseFiles=['LICENSE.txt','THIRD_PARTY_NOTICES.txt','licenses/manifest.json','licenses/dependency-inventory.json',...noticeManifest.files.map(item=>'licenses/'+item.file)];
for(const name of licenseFiles)assert.deepEqual(fs.readFileSync(path.join(legal,name)),fs.readFileSync(path.join(prepared,name)),name);
assert.equal(crypto.createHash('sha256').update(fs.readFileSync(path.join(root,'release/win-unpacked/LICENSES.chromium.html'))).digest('hex'),noticeManifest.electron_runtime_notices.sha256);
assert.deepEqual(fs.readFileSync(path.join(root,'release/win-unpacked/LICENSE.electron.txt')),fs.readFileSync(path.join(root,'licenses/Electron-37.10.3.txt')));
assert.deepEqual(fs.readFileSync(path.join(root, 'build/core/qq-insight-core.exe')), fs.readFileSync(path.join(root, 'release/win-unpacked/resources/core/qq-insight-core.exe')));
const name = `QQ-Insight-${sourcePackage.version}-portable.exe`;
const hash = crypto.createHash('sha256').update(fs.readFileSync(path.join(root, 'release', name))).digest('hex');
assert.ok(fs.readFileSync(path.join(root, 'release/SHA256.txt'), 'utf8').includes(`${hash}  ${name}`), 'postdist checksums include current release');
console.log(`Verified ${sourcePackage.version}: all desktop files and packaged core match; SHA256 ${hash}`);
