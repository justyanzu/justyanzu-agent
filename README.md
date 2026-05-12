# justyanzu-agent
从agenticSeek项目开始学

第一部分：Agent 的核心原理（打破黑盒）
1. 疑问：Agent 到底是怎么用代码实现的？只是大模型调工具吗？
- 核心认知：
  - Agent 不是一个简单的函数，而是一个 “感知 (Observation) -> 思考 (Thought) -> 行动 (Action)” 的无限循环（Loop）。
  - ReAct 模式（Reasoning + Acting）： 
  思考 (Thought)： LLM 分析用户问题，决定是否需要用工具。
  行动 (Action)： 如果需要，LLM 生成特定格式的文本（比如 Action: Search）。
  执行 (Observation)： Python 代码 捕获这个关键字，运行对应的函数，拿到结果。
  再思考 (Response)： 把函数运行的结果，喂回给 LLM，让它基于结果继续回答。
  - 实现逻辑： While True 循环 + 历史记录追加（Memory）。
2. 疑问：在真实代码中，怎么判断“要不要调工具”？
- 核心认知：
  - 旧方法： 靠正则匹配字符串（匹配用户提问的关键词）。
  - 新方法： 靠 API 原生的 Function Calling。API 返回的 JSON 里会有专门的 tool_calls 字段，不用猜。
3. 疑问：大模型怎么知道参数是多少（比如 order_id=1001）？
- 核心认知：
  - 槽位填充 (Slot Filling)： 依靠这时候我们传给大模型的 Schema (工具说明书)。
  - 大模型利用语义理解能力，把自然语言里的信息（“1001号订单”）提取出来，填入 Schema 定义好的参数坑位里。
4. 疑问：本地大模型返回的是 Markdown 还是 JSON？需要转化吗？
- 核心认知 (数据流)：
  - 大模型 (大脑) 生成的是 Markdown 格式的纯字符串。
  - API (快递员) 把这个字符串装进 JSON 盒子 (content 字段) 传给 Python。
  - Python 代码 拆开 JSON，拿出字符串，利用 Tag（如 ```python）定位并提取代码。

---
第二部分：本地部署与架构（AgenticSeek 项目实战）
5. 疑问：Ollama / LM Studio 是什么？和 OpenAI 库有什么区别？
- 核心认知：
  - OpenAI 库 = 遥控器/协议（负责发指令）。
  - Ollama = 本地主机/引擎（负责下载模型、跑模型）。
  - AgenticSeek 的魔法： 用 OpenAI 的遥控器，控制本地的 Ollama 主机（通过修改 base_url）。
6. 疑问：Docker 和 SearxNG 是什么？
- 核心认知：
  - Docker = 虚拟集装箱。它把复杂的软件环境打包（镜像），让你可以一键启动，不用担心环境报错。
  - SearxNG = Agent 的眼睛。一个本地运行的隐私聚合搜索引擎，解决 Google 反爬和收费问题。
7. 疑问：config.ini 和 .env 是干嘛的？
- 核心认知：
  - .env (通讯录)： 存地址、密码、路径（在哪里找服务）。
  - config.ini (大脑设置)： 存行为逻辑（用什么模型、是否隐身、人设是什么）。
  - 读取逻辑： 程序启动时先“查字典”（Read Config），再根据字典里的指引去“定位”（Get Path）。
8. 疑问：我的 8GB 显存能跑吗？
- 核心认知：
  - 瓶颈： Agent 需要推理能力强的模型（14B+），8GB 显存跑 14B 会很卡。
  - 方案： 勉强跑 7B（可能笨），或者改用云端 DeepSeek API（便宜且强）。

---
第三部分：源码级理解（Tool 类的本质）
9. 疑问：为什么 config.ini 里没写工具有哪些？
- 核心认知：
  - 硬编码： 核心工具（浏览器、代码解释器）通常直接写在 Python 代码里，因为它们是 Agent 的基础能力，不需要用户配置。
10. 疑问：tools.py 这个基类文件在干嘛？
- 核心认知：
  - __init__： 查户口，定地盘（工作目录）。
  - load_exec_block： 翻译官。用 assert 做安全检查，用 Tag 确定目标，从 Markdown 里抠出代码。
  - @abstractmethod： 霸王条款。父类规定子类必须实现的接口（execute）。
11. 疑问：execution_failure_check 和 interpreter_feedback 是干嘛的？
- 核心认知：
  - 自我反思机制：
    - Check： 质检员，判断刚才运行是成是败。
    - Feedback： 教练，把报错信息翻译成“建议”，哄大模型去修 Bug。
12. 疑问：这些 Tool 类是不是都得程序员手写？
- 核心认知：
  - 是的。
  - 分工： 程序员是铸剑师（构建物理世界接口），AI 是剑客（决定何时拔剑）。
  - Agent 工程师现状： 80% 的时间在写工具逻辑、清洗数据、写 Prompt 说明书，用确定性的代码包裹不确定性的 AI。
2.24 一些理解：
用户-》大模型查看skills-》大模型输出skills中规定格式的内容-》loop循环发现大模型输出的是这种规定格式内容-》执行对应工具-》工具调用返回结果给大模型-》大模型根据工具调用的返回结果-》用户

其中loop循环是一大关键 之前在学习agentseek项目时 问过ai大模型一些相关的 有使用while循环的，不过规范好像大多使用langchain。
 
2.25：例子：用Python写一个贪吃蛇小游戏
1.接收请求并传递给大模型进行思考
api.py中post /query接收请求  ->>执行process_query，is_generating变量判断服务器是否在生成（相当于锁）
->>服务器没在生成则调用think_wrapper，think_wrapper传入interaction对象（大模型思考的核心，来自interaction.py），调用interaction.think()进行思考回答

2.

Async def 是什么函数呢？->>抽象方法 强制子类处理逻辑

3.2
让我们来梳理一下整个流程

用户输入问题---》router路由判断转交哪个agent（1.翻译用户问题，cause少样本分类器few-shot用的shots是英文，英文准确率高 2.基于huggingface adaptive-classifier可训练分类器，加入few-shots分类器对复杂度和任务类别进行分类，再使用一个bart零分类模型（需要传入分类类别）对问题进行复杂度和任务类别分类，两个分数加权归一化）


为什么要用两个分类器分类呢
答：涉及到冷门，新颖，bart可能不能很好分类，少样本的可训练分类器能很好弥补，属于互补，本质是对任务进行分类，多agent，
为什么大模型训练用英文呢？与transformer有关系没


与manus,openclaw的区别？优势？

 利用ThreadPool（线程池）+异步等待解决llm请求并发问题，http异步库解决http并发问题（当socket接受后，await 去取数据）

agent.py中的关键： 
  llm请求：llm.respond(memory, self.verbose)  调用大模型，传入参数为memory和日志 verbose，再把推理和答案分开（依据大模型返回块的tag），把答案再加入memory.push中
    memory：
      1.首先对模型上下文进行估算，7B模型通常具有4096 token 的上下文窗口，读取模型名称获取模型参数量
        2.上下文压缩采用一个基于LED的上文本摘要提取模型
        3.记忆是按agent类别存储的，json，这种设计有利于不同角色或功能的 agent 保持独立的对话历史，避免相互干扰。  openclaw是如何做的呢？（也是分）
        4.将对话加入到记忆列表：Push memory时，先估算上下文窗口，若本次信息超过则压缩，返回Push后的记忆列表索引
        5.summerise:先用模型的tokenizer分词器将文本编码pytroch张量，再用模型的generate生成摘要，再解码张量返回
        6.何时加载何时保存何时push：初始化启动时，config设置参数load_last_session=True,各agent分别加载对应Memory，当一轮对话请求结束，由interaction统一调用各agent保存，注意区分push和保存，push是每个agent在请求时就把memory push到内存中，当interaction判断整个请求结束了才调用agent把memory保存到硬盘中。
        7.一轮对话会生成一个新的 memory 文件；
这个文件是“当前整个 session 到此为止的快照”。
开启 recover_last_session 时，新一轮运行即程序初始启动会在启动时加载上个 session 的最后一份快照，每轮对话都在次基础上添加memory。
      llm_provider:
      1.load_dotenv(),解决我一直来的疑问：如何读到.env中的配置的：
            读取项目根目录下的 .env 文件，将其中的键值对加载到系统环境变量中，然后通过getenv(键名),得到系统环境变量中的配置值。
      2.respond(history,vibose)：真正的调用模型的函数，比如ollama，就会调用ollama_fn
        ollama_fn(history,vibose)->str:
          1.构建ollama服务地址：env的internal_url+端口号，或者远程服务器地址
             2.构建Ollama客户端；client(host)
            3.流式聊天：scream=cient.chat,  for chunk in scream: 遍历输出的每一个块，其中Message字典中的content就是大模型输出的文本，拼接起来
  
  execute_modules：
    Tools:
      1.load_exec_block():加载每个工具要处理的对应块，比如写代码的工具，块tag=python，找到提取首尾索引提取，提取时需要处理缩进问题：（markdown标题会影响缩进从而影响代码）
            2.exec，python内置函数，动态执行代码块字符串，即load_exec_block提取出的块

browseragent：
  1.第一轮将用户问题和预设关键词结合传给大模型，如果大模型判断要搜索，searxng工具就像是把要搜索的内容输入到浏览器搜索框中，然后搜索框中出现了一些相关的网页，把这些网页的标题，链接，摘要整理成列表，再把这些信息和预设关键词结合，
  2.然后开始循环，把内容传给大模型，大模型根据提示词要求，选择要填什么表单，要点什么链接，是否觉得已经满足所需要的信息了，然后循环中根据正则式判断大模型要填什么表单，填完后把页面内容发给大模型，判断Action.FORM_FILLED了说明大模型觉得表单填好了，这时就把页面文本和链接发给大模型，然后逐行检查大模型输出，如果有链接，就提出来用browser中的函数点，然后获取新页面信息又与预设关键词结合，再发送给大模型，直到大模型觉得完成了
     3.如何判断该退出了呢：当大模型按照提示词规定在输出中输出了Action.REQUEST_EXIT.value时


所以每个agent的执行就是 把用户的提示词push进memory，然后请求llm，llm会根据一开始初始化的agent中提供的工具，写对应工具的代码块，然后我们提取出代码块执行，最后返回的是去除代码块后的内容。
对每个块的执行：


场景不同，agent不同架构有不同的优势：
1.react:动态规划，没有明确实现路径，高容错发挥底层大模型能力。
      2.plan-and-execute:节省，任务流程标准化。
      3.autogpt：就像名称，全自动，黑盒，黑洞。与前两者最大区别是，会推翻历史。前两者均会建立在上一个任务成功的基础上。


plan有最大重试次数，plan失败就降级直接交由casual_agent处理
json_schema是需要大模型支持的。
使用json_schema 强制大模型strict按工具调用的 限制大模型生成的token集合，让大模型无法生成不符合格式的token。   但是强制要求模型输出可能会导致语法正确但模型生成效果不好（语义偏离）， 因此用pydantic定义带有业务规则的schema进行语义的规范进行互补。

Logit mask 工具。

结果校验：
1.任务错分配：
      2.任务依赖死锁：A任务依赖B任务输出 B任务依赖A任务输出，

为什么query改写：口语化，指代词，大模型去结合上下文补全用户意图，尽可能将语义靠近知识库，提升效果嘛。
query改写：标准化，扩展多个语义相近，复杂问题拆解。 

多路检索

redis做缓存：大量多次读取磁盘的场景：如skill的读取，类似os的cpu内存管理，先通过hash查询redis客户端，cache未命中则从磁盘读入，可以减少高频的skill读取磁盘消耗。
