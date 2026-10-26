const { app, BrowserWindow } = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

app.whenReady().then(async () => {
  const win = new BrowserWindow({ show: false, width: 1540, height: 1100, webPreferences: { offscreen: true, backgroundThrottling: false, contextIsolation: true, nodeIntegration: false } });
  try {
    await win.loadFile(path.join(__dirname, '../src/desktop/renderer/index.html'));
    const result = await win.webContents.executeJavaScript(`(async () => {
      const initialMenu={closed:!$('#conversation-tools').open,groups:!!$('#conversation-tools #export-groups'),groupExports:$('#conversation-tools [data-export="members"]')!==null};
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
      },exportRoster:async input=>{calls.push({method:'roster.export',params:input});return {count:2,note:'本地合成名单'};},exportFullRoster:async input=>{calls.push({method:'roster.export',params:input});return {count:3,note:'官网合成名单含未发言者'};},saveSettings:async input=>(state.settings={...state.settings,...input})};
      const tick=()=>new Promise(resolve=>setTimeout(resolve,30));
      $('#toast').className='toast'; $('#core-state').textContent='合成测试核心';
      $('#message-mode').value='all'; $('#message-order').value='desc';
      $('#message-query').value='报告'; $('#message-sender').value='合成';
      await openConversation(group.id); await tick();
      const query=calls.find(item=>item.method==='message.list').params;
      const groupButtons=$('#message-header').querySelectorAll('[data-open-ai]').length;
      const menu=$('#conversation-tools');
      const visibleActions=[...$('#message-header').querySelectorAll('button,summary')].filter(node=>node.checkVisibility()).map(node=>node.textContent.trim());
      const exportsHidden=[...menu.querySelectorAll('[data-export]')].every(node=>!node.checkVisibility());
      const exportFromMenu=async kind=>{
        $('#conversation-tools summary').click();
        const button=$('#conversation-tools [data-export="'+kind+'"]');
        if(!button.checkVisibility())throw new Error('Export menu item must be visible');
        button.click();await tick();
        if($('#conversation-tools').open)throw new Error('Menu must close after selection');
      };
      await exportFromMenu('members');await exportFromMenu('groups');
      await exportFromMenu('full_members');await exportFromMenu('cached_members');
      const rosterCalls=calls.filter(item=>item.method==='roster.export');
      menu.querySelector('summary').click();
      document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
      const escapeClosed=!menu.open&&document.activeElement===menu.querySelector('summary');
      menu.querySelector('summary').click();$('#message-list').click();
      const outsideClosed=!menu.open;
      const originalOpenAI=openConversationAgent;const aiTabs=[];
      openConversationAgent=(id,tab)=>aiTabs.push({id,tab});
      for(const tab of ['settings','history']) {menu.querySelector('summary').click();menu.querySelector('[data-open-ai="'+tab+'"]').click();}
      $('#message-header [data-open-ai="analysis"]').click();openConversationAgent=originalOpenAI;
      menu.querySelector('summary').click();
      const second={...group,id:'second-group',title:'第二个合成群'};state.conversations.push(second);
      await openConversation(second.id);
      const switchClosed=!$('#conversation-tools').open;
      await exportFromMenu('members');
      const secondExport=calls.filter(item=>item.method==='roster.export').at(-1).params;
      $('#conversation-tools summary').click();
      state.settings.activeAccountId='other-account';state.activeConversation=null;
      const beforeSwitch=calls.filter(item=>item.method==='roster.export').length;
      $('#conversation-tools [data-export="members"]').click();await tick();
      const staleBlocked=calls.filter(item=>item.method==='roster.export').length===beforeSwitch;
      await loadMessages();await exportFromMenu('groups');
      const accountExport=calls.filter(item=>item.method==='roster.export').at(-1).params;
      state.settings.activeAccountId='synthetic';state.activeConversation=group.id;
      $('#message-scope').value='account';await loadMessages();
      const accountOnly=$('#conversation-tools').querySelectorAll('[data-export]').length===1&&!$('#message-header [data-open-ai]');
      state.conversations.push({id:'private',title:'合成私聊',kind:'c2c'});await openConversation('private');
      const privateOnly=$('#conversation-tools').querySelectorAll('[data-export]').length===1&&$('#message-header [data-open-ai]').textContent==='AI聊天';
      await openConversation(group.id);
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
      return {initialMenu,visibleActions,exportsHidden,escapeClosed,outsideClosed,aiTabs,switchClosed,secondExport,staleBlocked,accountExport,accountOnly,privateOnly,query,groupButtons,hollow,yellow,favoritesCount,context,pinned,size,rosterCalls};
    })()`);
    assert.deepEqual(result.initialMenu,{closed:true,groups:true,groupExports:false});
    assert.deepEqual(result.visibleActions,['AI聊天','其他功能 ⌄']);
    for(const key of ['exportsHidden','escapeClosed','outsideClosed','switchClosed','staleBlocked','accountOnly','privateOnly']) assert.equal(result[key],true,key);
    assert.deepEqual(result.aiTabs,['settings','history','analysis'].map(tab=>({id:'synthetic-group',tab})));
    assert.equal(result.secondExport.conversation_id,'second-group');
    assert.equal(result.secondExport.account_id,'synthetic');
    assert.equal(result.accountExport.account_id,'other-account');assert.equal(result.accountExport.conversation_id,'');
    assert.equal(result.query.order,'desc'); assert.equal(result.query.limit,40);
    assert.equal(result.query.recent,false); assert.equal(result.query.query,'报告');
    assert.equal(result.groupButtons,3);
    assert.deepEqual(result.rosterCalls.map(x=>x.params.kind),['members','groups','full_members','cached_members']);
    assert.equal(result.rosterCalls[0].params.conversation_id,'synthetic-group');
    assert.equal(result.rosterCalls[0].params.account_id,'synthetic');
    assert.equal(result.hollow,'☆'); assert.equal(result.yellow.text,'★');
    assert.equal(result.yellow.color,'rgb(247, 191, 58)'); assert.equal(result.yellow.toast,'已加入收藏');
    assert.equal(result.favoritesCount,1);
    assert.deepEqual(result.context,{id:'synthetic-old',query:'',sender:'',disabled:true,variants:false});
    assert.equal(result.pinned,true); assert.equal(result.size,60);
    await new Promise(resolve=>setTimeout(resolve,200));
    fs.writeFileSync(path.join(__dirname,'../build/qa/workspace.png'),(await win.webContents.capturePage()).toPNG());
    await win.webContents.executeJavaScript(`$('#conversation-tools summary').click();`);
    await new Promise(resolve=>setTimeout(resolve,250));
    fs.writeFileSync(path.join(__dirname,'../build/qa/workspace-tools.png'),(await win.webContents.capturePage()).toPNG());
    await win.setSize(1200,1000);
    const compact=await win.webContents.executeJavaScript(`(() => {
      const panel=$('.conversation-tools-panel').getBoundingClientRect();const workspace=$('.workspace-grid').getBoundingClientRect();
      return {fits:panel.left>=workspace.left&&panel.right<=innerWidth&&panel.bottom<=workspace.bottom,scrollable:$('.conversation-tools-panel').scrollHeight>0};
    })()`);
    assert.equal(compact.fits,true);assert.equal(compact.scrollable,true);
    win.setSize(1540,1100);
    await win.webContents.executeJavaScript(`$('#conversation-tools').open=false;`);
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
    console.log('Workspace renderer passed: compact actions, four exports via menu, close/focus, group/account/private scopes, narrow layout, filtered order/page size, stars/favorites, context and pin.');
  } catch(error) { console.error(error); process.exitCode=1; }
  finally { win.destroy(); app.quit(); }
});
