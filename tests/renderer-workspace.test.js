const { app, BrowserWindow } = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

app.whenReady().then(async () => {
  const win = new BrowserWindow({ show: false, width: 1540, height: 1100, webPreferences: { offscreen: true, backgroundThrottling: false, contextIsolation: true, nodeIntegration: false } });
  try {
    await win.loadFile(path.join(__dirname, '../src/desktop/renderer/index.html'));
    const result = await win.webContents.executeJavaScript(`(async () => {
      state.settings={activeAccountId:'synthetic',activePlatform:'qq',messagePageSize:40,modelProfiles:[]};
      const group={id:'synthetic-group',title:'合成项目群',kind:'group',pinned:false,message_count:400};
      state.conversations=[group]; state.activeConversation=group.id;
      const target={id:'synthetic-old',conversation_id:group.id,sent_at:1700000000,direction:'incoming',sender_name:'合成成员',text:'请在周五前提交报告',content_kind:'文本',media:[],replies:[{sender:'合成引用人',text:'报告要求'}]};
      const calls=[]; let favorite=false; let savedRole='本群项目负责人';
      window.qqInsight={rpc:async(method,params)=>{
        calls.push({method,params});
        if(method==='message.list'||method==='message.search') return {items:[{...target,favorite}],has_more:true,next_cursor:{sent_at:1700000000,id:'next'}};
        if(method==='message.context') return {items:[{...target,favorite}],target_id:target.id,conversation:group,variants:[{text:'另一电脑保留的正文副本'}]};
        if(method==='profile.get') return {role_text:savedRole,fallback_role:'全局普通成员'};
        if(method==='profile.save') {savedRole=params.role_text; return {};}
        if(method==='favorite.set') {favorite=params.enabled;return {favorite};}
        if(method==='favorite.list') return {items:favorite?[{...target,favorite,favorite_media_index:-1}]:[],has_more:false};
        if(method==='conversation.pin') {group.pinned=params.pinned;return {pinned:group.pinned};}
        if(method==='conversation.list') return {items:[group],next_cursor:null};
        if(method==='insights.work_digest') return {summary:'合成线索',items:[{...target,conversation:group.title,role_context:savedRole,relevance:'待核实',due_hint:'周五'}],coverage_note:'合成数据测试'};
        return {};
      },saveSettings:async input=>(state.settings={...state.settings,...input})};
      const tick=()=>new Promise(resolve=>setTimeout(resolve,30));
      $('#toast').className='toast'; $('#core-state').textContent='合成测试核心';
      $('#message-mode').value='all'; $('#message-order').value='desc';
      $('#message-query').value='报告'; $('#message-sender').value='合成';
      await openConversation(group.id); await tick();
      const query=calls.find(item=>item.method==='message.list').params;
      const groupButtons=$('#message-header').querySelectorAll('[data-open-ai]').length;
      const star=$('#message-list [data-favorite]');
      const hollow=star.textContent; star.click(); await tick();
      const yellow={text:star.textContent,color:getComputedStyle(star).color,toast:$('#toast').textContent};
      showView('favorites'); await tick();
      const favoritesCount=$('#favorites-list').querySelectorAll('.message-row').length;
      await openMessageContext(target.id); await tick();
      const context={id:$('.context-target')?.dataset.messageId,query:$('#message-query').value,sender:$('#message-sender').value,disabled:$('#message-older').disabled,variants:$('.context-target').textContent.includes('另一电脑')};
      showPinMenu({preventDefault(){},clientX:500,clientY:150},group); $('#pin-menu').click();await tick();
      const pinned=$('.conversation-item').textContent.includes('📌');
      $('#message-page-size').value='60'; $('#save-history-settings').click();await tick();
      const size=state.settings.messagePageSize;
      showView('conversations'); await loadMessages(); await tick();
      document.getAnimations().forEach(animation=>animation.finish()); $('#toast').className='toast';
      return {query,groupButtons,hollow,yellow,favoritesCount,context,pinned,size};
    })()`);
    assert.equal(result.query.order,'desc'); assert.equal(result.query.limit,40);
    assert.equal(result.query.recent,false); assert.equal(result.query.query,'报告');
    assert.equal(result.groupButtons,3);
    assert.equal(result.hollow,'☆'); assert.equal(result.yellow.text,'★');
    assert.equal(result.yellow.color,'rgb(247, 191, 58)'); assert.equal(result.yellow.toast,'已加入收藏');
    assert.equal(result.favoritesCount,1);
    assert.deepEqual(result.context,{id:'synthetic-old',query:'',sender:'',disabled:true,variants:false});
    assert.equal(result.pinned,true); assert.equal(result.size,60);
    await new Promise(resolve=>setTimeout(resolve,200));
    fs.writeFileSync(path.join(__dirname,'../build/qa/workspace.png'),(await win.webContents.capturePage()).toPNG());
    const imageResult = await win.webContents.executeJavaScript(`(async () => {
      const source='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=';
      window.qqInsight.rpc=async method=>method==='media.read'?{available:true,data_url:source}:{};
      renderMessages([{id:'synthetic-image',text:'图片合成测试',direction:'incoming',media:[{type:'image',filename:'中文#图片.png'}]}],$('#message-list'));
      $('#message-list').scrollIntoView({block:'center'});
      for(let i=0;i<30;i++) { await new Promise(resolve=>setTimeout(resolve,50)); if(!$('.message-media').classList.contains('unavailable')) break; }
      const img=$('.message-media img');
      return {loaded:!img.hidden && img.naturalWidth===1,name:img.alt};
    })()`);
    assert.deepEqual(imageResult,{loaded:true,name:'中文#图片.png'});
    console.log('Workspace renderer passed: filtered order/page size, stars/favorites, old-message context, role, right-click pin.');
  } catch(error) { console.error(error); process.exitCode=1; }
  finally { win.destroy(); app.quit(); }
});
