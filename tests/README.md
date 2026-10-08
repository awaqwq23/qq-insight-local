# 当前测试

核心：设置 PYTHONPATH=src/core，Python unittest discover -s src/core/tests。
桌面：npm run test:desktop。
界面：package.json 的 test:history-ui、workspace-ui、transfer-ui、ai-ui、media-ui、budget-ui。
打包：python tests/packaged-core-smoke.py。

benchmark 为可复用合成基准；live 测试可能产生模型费用，仅明确授权时运行。
不将真实消息、账号、密钥或 API Key 写入仓库。
