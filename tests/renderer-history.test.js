const { app, BrowserWindow } = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

app.whenReady().then(async () => {
  const win = new BrowserWindow({ show: false, width: 1540, height: 1000, webPreferences: { offscreen: true, backgroundThrottling: false, contextIsolation: true, nodeIntegration: false } });
  try {
    await win.loadFile(path.join(__dirname, '../src/desktop/renderer/index.html'));
    const result = await win.webContents.executeJavaScript(`(async () => {
      state.settings = {activeAccountId:'synthetic-a',activePlatform:'qq'};
      state.conversations = [{id:'synthetic-chat',title:'合成测试会话',kind:'c2c',message_count:205}];
      $('#core-state').textContent='合成测试核心'; $('#toast').className='toast';
      const requests = [];
      window.qqInsight = {rpc: async (method, params) => {
        requests.push({method,params});
        const offset = params.cursor ? Number(params.cursor.id) : 0;
        const size = params.query === '不存在' ? 0 : Math.min(100,205-offset);
        return {items:Array.from({length:size},(_,i)=>({id:String(offset+i),sent_at:1700000000+offset+i,direction:'incoming',sender_name:'测试成员',sender_qq:'000000',title:'合成测试会话',text:'合成消息 '+(offset+i),content_kind:'文本',parse_status:'partial'})),has_more:offset+size<205 && size>0,next_cursor:offset+size<205 && size>0?{sent_at:1700000000,id:String(offset+size)}:null};
      }};
      await openConversation('synthetic-chat');
      const recent = {count:document.querySelectorAll('.message-row').length,older:$('#message-older').disabled};
      $('#message-mode').value='all'; resetMessagePages(); await loadMessages();
      state.messageCursors[1]=state.messageNext; await loadMessages(1);
      const second = $('#message-page-state').textContent;
      state.messageCursors[2]=state.messageNext; await loadMessages(2);
      const last = {count:document.querySelectorAll('.message-row').length,older:$('#message-older').disabled,newer:$('#message-newer').disabled};
      $('#message-scope').value='account'; $('#message-query').value='测试成员'; $('#message-sender').value='000000'; resetMessagePages(); await loadMessages();
      const search = requests.at(-1);
      $('#message-query').value='不存在'; resetMessagePages(); await loadMessages();
      const empty = $('#message-list').textContent;
      $('#message-query').value=''; $('#message-sender').value=''; resetMessagePages(); await loadMessages();
      const testRpc=window.qqInsight.rpc;
      let resolveOld;
      window.qqInsight.rpc=()=>new Promise(resolve=>{resolveOld=resolve});
      const pending=loadMessages(); resetMessagePages(); $('#message-list').textContent='新账号内容';
      resolveOld({items:[{text:'stale'}],has_more:false}); await pending;
      const staleIgnored=$('#message-list').textContent==='新账号内容';
      window.qqInsight.rpc=testRpc; resetMessagePages(); await loadMessages();
      const defaultImportMode = $('#import-mode').value;
      const importRequests = [];
      window.qqInsight.prepareSource = async input => {
        importRequests.push(input);
        if (input.confirmed) throw new Error('synthetic failure');
        return {requiresConfirmation:true,automaticKeyExtraction:false,message:'合成更新确认'};
      };
      $('#import-mode').value='full';
      await prepareSource('synthetic-source');
      const fullNotice=$('#decrypt-message').textContent;
      await confirmDecrypt();
      closeDecryptModal(); $('#toast').className='toast'; $('#import-mode').value='incremental';
      const importSummary=importResultMessage({status:'updated',import_mode:'incremental',changes:{added:20,updated:1},metadata:{profiles:1}});
      const color=getComputedStyle($('#confirm-decrypt')).backgroundColor;
      return {recent,second,last,search,empty,staleIgnored,color,defaultImportMode,importRequests,fullNotice,importSummary};
    })()`);
    assert.deepEqual(result.recent, { count: 100, older: true });
    assert.match(result.second, /第 2 页/);
    assert.deepEqual(result.last, { count: 5, older: true, newer: false });
    assert.equal(result.search.method, 'message.search');
    assert.equal(result.search.params.sender, '000000');
    assert.equal(result.search.params.account_id, 'synthetic-a');
    assert.match(result.empty, /没有符合条件/);
    assert.equal(result.staleIgnored, true);
    assert.equal(result.color, 'rgb(200, 50, 69)');
    assert.equal(result.defaultImportMode, 'incremental');
    assert.deepEqual(result.importRequests.map(input => input.importMode), ['full', 'full']);
    assert.match(result.fullNotice, /全量/);
    assert.match(result.importSummary, /新增 20 条，变化 1 条，更新资料 1 项/);
    fs.mkdirSync(path.join(__dirname, '../build/qa'), { recursive: true });
    await new Promise(resolve => setTimeout(resolve, 350));
    fs.writeFileSync(path.join(__dirname, '../build/qa/history.png'), (await win.webContents.capturePage()).toPNG());
    await win.webContents.executeJavaScript("$('#decrypt-modal').classList.add('visible'); $('#decrypt-message').textContent='使用已保存的密钥读取本机已有记录。';");
    await new Promise(resolve => setTimeout(resolve, 350));
    fs.writeFileSync(path.join(__dirname, '../build/qa/confirm.png'), (await win.webContents.capturePage()).toPNG());
    console.log('Renderer history tests passed: recent/all, 3 pages, scoped search, empty state, stale response, red confirmation');
  } catch (error) {
    console.error(error);
    process.exitCode = 1;
  } finally {
    win.destroy();
    app.quit();
  }
});
