async function commandClient(webSocketUrl) {
  const socket = new WebSocket(webSocketUrl);
  await new Promise((resolve, reject) => {
    socket.onopen = resolve;
    socket.onerror = reject;
  });
  let requestId = 0;
  const waiting = new Map();
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (!message.id || !waiting.has(message.id)) return;
    waiting.get(message.id)(message);
    waiting.delete(message.id);
  };
  return {
    evaluate(expression) {
      return new Promise((resolve, reject) => {
        const id = ++requestId;
        waiting.set(id, (message) => {
          if (message.result?.exceptionDetails) reject(new Error(message.result.exceptionDetails.text));
          else resolve(message.result.result.value);
        });
        socket.send(JSON.stringify({ id, method: 'Runtime.evaluate', params: { expression, returnByValue: true } }));
      });
    },
    close: () => socket.close(),
  };
}

async function main() {
  const port = process.argv[2] || '9333';
  const pages = await fetch(`http://127.0.0.1:${port}/json/list`).then((response) => response.json());
  const page = pages.find((item) => item.type === 'page');
  if (!page) throw new Error('没有找到 Electron 渲染页面');
  const client = await commandClient(page.webSocketDebuggerUrl);
  const defaults = JSON.parse(await client.evaluate(
    `JSON.stringify([...document.querySelectorAll('#model-profile-tabs .profile-tab span')].map((node) => node.textContent))`,
  ));
  if (!defaults.includes('OpenAI') || !defaults.includes('Anthropic / Claude')) {
    throw new Error(`默认模型接口不完整：${defaults.join(', ')}`);
  }
  const paging = JSON.parse(await client.evaluate(
    `state.modelCatalog={profileId:'openai-default',models:Array.from({length:25},(_,i)=>'model-'+String(i+1).padStart(2,'0')),page:0};renderModelCatalog();JSON.stringify({shown:document.querySelectorAll('.model-result').length,page:document.querySelector('#model-page-state').textContent,nextDisabled:document.querySelector('#model-page-next').disabled})`,
  ));
  if (paging.shown !== 18 || paging.page !== '第 1 / 2 页' || paging.nextDisabled) {
    throw new Error(`模型分页不正确：${JSON.stringify(paging)}`);
  }
  client.close();
  console.log(`renderer smoke passed: defaults=${defaults.join(' / ')}, ${paging.page}, shown=${paging.shown}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
