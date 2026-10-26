const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),source=path.join(root,'licenses'),target=path.join(root,'build/legal');
const manifest=JSON.parse(fs.readFileSync(path.join(source,'manifest.json'),'utf8'));
const hash=file=>crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
assert.equal(manifest.version,JSON.parse(fs.readFileSync(path.join(root,'package.json'),'utf8')).version);
assert.ok(fs.readFileSync(path.join(root,'LICENSE'),'utf8').startsWith('MIT License'));
const names=['manifest.json','dependency-inventory.json',...manifest.files.map(item=>item.file)];
assert.equal(new Set(names).size,names.length);
for(const name of names)assert.ok(name===path.basename(name)&&!name.includes('..'),'License filenames must stay inside the notice directory');
for(const item of manifest.files)assert.equal(hash(path.join(source,item.file)),item.sha256,item.file);
assert.equal(hash(path.join(root,'node_modules/electron/dist/LICENSES.chromium.html')),manifest.electron_runtime_notices.sha256);
fs.mkdirSync(path.join(target,'licenses'),{recursive:true});
// Reject unexpected old output rather than copying unrelated local files into a release.
for(const name of fs.readdirSync(target))assert.ok(['LICENSE.txt','THIRD_PARTY_NOTICES.txt','licenses'].includes(name),'Unexpected legal output');
for(const name of fs.readdirSync(path.join(target,'licenses')))assert.ok(names.includes(name),'Unexpected legal source');
fs.copyFileSync(path.join(root,'LICENSE'),path.join(target,'LICENSE.txt'));
fs.copyFileSync(path.join(root,'THIRD_PARTY_NOTICES.md'),path.join(target,'THIRD_PARTY_NOTICES.txt'));
for(const name of names)fs.copyFileSync(path.join(source,name),path.join(target,'licenses',name));
console.log(`Prepared ${manifest.files.length} original license texts, dependency inventory and user-readable notices.`);
