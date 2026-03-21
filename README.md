# 🚀 Xianyu AutoAgent - 智能闲鱼客服机器人系统

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/) [![LLM Powered](https://img.shields.io/badge/LLM-powered-FF6F61)](https://platform.openai.com/)

专为闲鱼平台打造的AI值守解决方案，实现闲鱼平台7×24小时自动化值守，支持多专家协同决策、智能议价和上下文感知对话。 


## 🌟 核心特性

### 智能对话引擎
| 功能模块   | 技术实现            | 关键特性                                                     |
| ---------- | ------------------- | ------------------------------------------------------------ |
| 上下文感知 | 会话历史存储        | 轻量级对话记忆管理，完整对话历史作为LLM上下文输入            |
| 专家路由   | LLM prompt+规则路由 | 基于提示工程的意图识别 → 专家Agent动态分发，支持议价/技术/客服多场景切换 |

### 业务功能矩阵
| 模块     | 已实现                        | 规划中                       |
| -------- | ----------------------------- | ---------------------------- |
| 核心引擎 | ✅ LLM自动回复<br>✅ 上下文管理 | 🔄 情感分析增强               |
| 议价系统 | ✅ 阶梯降价策略                | 🔄 市场比价功能               |
| 技术支持 | ✅ 网络搜索整合                | 🔄 RAG知识库增强              |
| 运维监控 | ✅ 基础日志                    | 🔄 钉钉集成<br>🔄  Web管理界面 |

## 🎨效果图
<div align="center">
  <img src="./images/demo1.png" width="600" alt="客服">
  <br>
  <em>图1: 客服随叫随到</em>
</div>


<div align="center">
  <img src="./images/demo2.png" width="600" alt="议价专家">
  <br>
  <em>图2: 阶梯式议价</em>
</div>

<div align="center">
  <img src="./images/demo3.png" width="600" alt="技术专家"> 
  <br>
  <em>图3: 技术专家上场</em>
</div>

<div align="center">
  <img src="./images/log.png" width="600" alt="后台log"> 
  <br>
  <em>图4: 后台log</em>
</div>


## 🚴 快速开始
小白请直接查看[保姆级教学文档](https://my.feishu.cn/wiki/JtkBwkI9GiokZikVdyNceEfZncE)
### 环境要求
- Python 3.8+

### 安装步骤
```bash
1. 克隆仓库
git clone https://github.com/shaxiu/XianyuAutoAgent.git
cd XianyuAutoAgent

2. 安装依赖
pip install -r requirements.txt

3. 配置环境变量
创建一个 `.env` 文件，包含以下内容，也可直接重命名 `.env.example` ：
#必配配置
API_KEY=apikey通过模型平台获取
COOKIES_STR=填写网页端获取的cookie（仅启动兜底）
COOKIE_FILE_PATH=data/cookies.txt
MODEL_BASE_URL=模型地址
MODEL_NAME=模型名称
#可选配置
MODEL_REASONING_EFFORT=全局默认推理强度，可选 none/minimal/low/medium/high/xhigh
CLASSIFY_MODEL_REASONING_EFFORT=意图分类Agent推理强度，优先级高于全局默认
PRICE_MODEL_REASONING_EFFORT=议价Agent推理强度，优先级高于全局默认
TECH_MODEL_REASONING_EFFORT=技术Agent推理强度，优先级高于全局默认
DEFAULT_MODEL_REASONING_EFFORT=默认回复Agent推理强度，优先级高于全局默认
TECH_ENABLE_SEARCH=True/False #技术Agent是否向模型转发enable_search，默认False
TOGGLE_KEYWORDS=接管模式切换关键词，默认为句号（输入句号切换为人工接管，再次输入则切换AI接管）
SIMULATE_HUMAN_TYPING=True/False #模拟人工回复延迟
FEISHU_NOTIFY_ENABLED=True/False #开启Cookie失效飞书告警（默认False）
FEISHU_WEBHOOK_URL=飞书机器人Webhook地址
FEISHU_APP_ID=飞书自建应用的 App ID
FEISHU_APP_SECRET=飞书自建应用的 App Secret
FEISHU_ADMIN_OPEN_IDS=允许提交 Cookie 的管理员 open_id，逗号分隔
FEISHU_CALLBACK_HOST=飞书回调服务监听地址，默认 127.0.0.1
FEISHU_CALLBACK_PORT=飞书回调服务监听端口，默认 8100
FEISHU_CALLBACK_PATH=飞书事件回调路径，默认 /feishu/events
FEISHU_CALLBACK_MODE=事件校验模式，当前版本建议使用 token
FEISHU_VERIFICATION_TOKEN=FEISHU_CALLBACK_MODE=token 时必填
FEISHU_ENCRYPT_KEY=FEISHU_CALLBACK_MODE=encrypt 时使用；当前构建不支持加密事件体
FEISHU_STALE_LOCK_SECONDS=单飞提交锁的过期秒数，默认 300

注意：当前版本统一使用 OpenAI `responses` 协议；如需使用其他 API，请确认服务端兼容 `responses` 请求格式，再修改 `.env` 文件中的模型地址和模型名称；
推理强度支持全局默认值，也支持按 Agent 单独覆盖，未配置时会自动回退到默认行为；
如果你的转发 API 不支持 `enable_search`，请保持 `TECH_ENABLE_SEARCH=False`；
COOKIES_STR自行在闲鱼网页端获取cookies(网页端F12打开控制台，选择Network，点击Fetch/XHR,点击一个请求，查看cookies)；
运行时Cookie实时来源为 `data/cookies.txt`，程序会优先读取该文件；
当Cookie失效并触发 `CookieInvalidError` 后，进程不会退出，会进入等待状态，更新 `data/cookies.txt` 后自动恢复连接；
运行时不会再回写 `.env` 中的 `COOKIES_STR`，`.env` 仅用于启动兼容兜底。
如果启用飞书私聊控制面，请把飞书事件订阅模式配置为 `token` 校验，并将回调 URL 指向 `https://<你的域名><FEISHU_CALLBACK_PATH>`；
版本 1 仅接受白名单管理员的私聊文本消息，不接受群聊提交，不会回显 Cookie 内容；
控制面会将提交状态写入 `data/cookie_submission_state.json`，主进程会将恢复状态写入 `data/runtime_status.json`；
同一时间只允许一个 Cookie 提交处于校验中，后续提交会收到“稍后重试”提示；
飞书重复回调会按 `event_id` / `message_id` 去重，避免重复写入和重复回复。

4. 创建提示词文件prompts/*_prompt.txt（也可以直接将模板名称中的_example去掉），否则默认读取四个提示词模板中的内容
```

### 使用方法

运行主程序：
```bash
python main.py
```

启动飞书控制面：
```bash
python -m services.feishu_control_plane
```

控制面启动后会打印一个手工校验命令，可直接用来验证本地服务和回调路径是否正确。

### 飞书 Cookie 控制面

1. 在飞书开放平台创建自建应用并启用机器人能力。
2. 在事件订阅中开启私聊消息事件，并把回调 URL 指向你的 HTTPS 域名加 `FEISHU_CALLBACK_PATH`。
3. 事件校验模式当前建议选择 `token`，并把同一个 token 写入 `FEISHU_VERIFICATION_TOKEN`。
4. 将允许操作的管理员 `open_id` 写入 `FEISHU_ADMIN_OPEN_IDS`。
5. 主进程 `python main.py` 和控制面 `python -m services.feishu_control_plane` 需要部署在同一台机器并共享项目目录下的 `data/`。

支持的私聊命令：

- `/help`：返回支持的命令说明
- `/status`：返回当前恢复状态、更新时间和最近一条运维提示
- 直接发送完整 Cookie 文本：写入 `data/cookies.txt` 并启动校验

回执行为：

- 接收成功后立即回复 `已接收，开始校验`
- 主进程恢复成功后回复 `Cookie 已生效，连接已恢复`
- 主进程校验失败后回复 `Cookie 已接收，但校验失败，请重新获取`
- 如果 60 秒内没有等到匹配的恢复结果，会回复超时提示

### 自定义提示词

可以通过编辑 `prompts` 目录下的文件来自定义各个专家的提示词：

- `classify_prompt.txt`: 意图分类提示词
- `price_prompt.txt`: 价格专家提示词
- `tech_prompt.txt`: 技术专家提示词
- `default_prompt.txt`: 默认回复提示词

## 🤝 参与贡献

欢迎通过 Issue 提交建议或 PR 贡献代码，请遵循 [贡献指南](https://contributing.md/)



## 🛡 注意事项

⚠️ 注意：**本项目仅供学习与交流，如有侵权联系作者删除。**

鉴于项目的特殊性，开发团队可能在任何时间**停止更新**或**删除项目**。

如需学习交流，请联系：[coderxiu@qq.com](https://mailto:coderxiu@qq.com/)

## 📱 交流群
欢迎加入项目交流群，交流技术、分享经验、互助学习。
<div align="center">
  <table>
    <tr>
      <td align="center"><strong>交流群18（已满200）</strong></td>
      <td align="center"><strong>交流群19（推荐加入）</strong></td>
    </tr>
    <tr>
      <td><img src="./images/wx_group18.png" width="300px" alt="交流群18"></td>
      <td><img src="./images/wx_group19.png" width="300px" alt="交流群19"></td>
    </tr>
  </table>
</div>

## 💼 寻找机会

### <a href="https://github.com/shaxiu">@Shaxiu</a>
**🔍寻求方向**：**AI产品经理**  
**📫 联系：** **email**:coderxiu@qq.com；**wx:** coderxiu

### <a href="https://github.com/cv-cat">@CVcat</a>
**🔍寻求方向**：**研发工程师**（python、java、逆向、爬虫）  
**📫 联系：** **email:** 992822653@qq.com；**wx:** CVZC15751076989
## ☕ 请喝咖啡
您的☕和⭐将助力项目持续更新：

<div align="center">
  <img src="./images/wechat_pay.jpg" width="400px" alt="微信赞赏码"> 
  <img src="./images/alipay.jpg" width="400px" alt="支付宝收款码">
</div>


## 📈 Star 趋势
<a href="https://www.star-history.com/#shaxiu/XianyuAutoAgent&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=shaxiu/XianyuAutoAgent&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=shaxiu/XianyuAutoAgent&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=shaxiu/XianyuAutoAgent&type=Date" />
 </picture>
</a>
