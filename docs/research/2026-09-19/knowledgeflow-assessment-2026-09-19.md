# KnowledgeFlow — 全方位评估报告

> 评估对象：`C:\Users\94233\knowledge-flow`（HEAD `88d75d4`，`main == origin/main`，122 个已跟踪文件）
> 评估日期：2026-09-19 · 评估方式：全量源码阅读 + 独立复核 + 实测运行（不改动任何项目文件）
> 本报告是一次**独立第三方评估**，不是项目文档的一部分；文中所有结论均标注 `文件:行` 或实测命令。

---

## 0. 执行摘要

### 0.1 一句话结论

**这是一个工程实现质量远超其方法论验证质量的项目。** 12,202 行 Python 构建的捕获内核（capture kernel）在原子性、崩溃恢复、错误分类、路径安全等方面达到了少见的水准，274 项测试全部通过；但**支撑整个项目立论的核心产物——策展地图（curation map）与覆盖报告——没有任何解析器、校验器、fixture 或 CI 覆盖**，仓库中唯一的样例明确声明自己无法给出覆盖报告。项目花了两年工程努力建造了一台精密的"写入机器"，却把"读取是否完整"这个真正的问题留在了 LLM 的自我报告里。

### 0.2 五维评分

| 维度 | 评分 | 一句话理由 |
|---|---|---|
| **捕获内核工程实现** | **A−** | 哈希绑定不可变事实、目录 rename 原子提交、31 个故障注入点、真实双进程竞争测试、错误分类基于证据而非异常类型 |
| **验证与测试基础设施** | **B** | 274 项测试零失败、真实 4/64 MiB 边界、崩溃恢复有磁盘状态断言；但**无覆盖率度量**、无属性测试、无 fuzz、61.3% 测试硬跳过非 Windows |
| **方法论 / 提示词层** | **D+** | 硬约束 C4 在提示词层完全丢失；覆盖报告的分辨率低于它要检测的失效模式；唯一的样例 §10 拒绝产出覆盖数据 |
| **文档与治理层** | **B−** | 主题级权威模型与 48 条冲突登记是真本事；但双语 README 不平行、归档文件贴错版本标签、84 个验收复选框未勾选 |
| **可交付性 / 可用性** | **F** | 四个操作**没有任何 CLI**，端到端流程不可执行；无生产配置、无生产 Store；README 自述"完整捕获 MVP 尚未实现" |

### 0.3 必须立即知道的五个事实（均已独立验证）

1. **测试套件在此环境下第一次运行报 274 项全错**（113 failures / 260 errors）。根因**不是项目缺陷**，是沙箱对 `os.mkdir(path, 0o700)` 的权限策略（`tempfile.mkdtemp` 硬编码 `0o700`）。修正后 **`Ran 274 tests ... OK`**，严格 `ResourceWarning` 模式同样 OK。
2. **热路径是 O(Store)**：实测 200 条捕获时，单次 `capture_text` 平均 **1560 ms**，`list_captures(limit=1)` 需 **7.4 秒**。`indexes/idempotency` 目录被创建但**从未被读写**。
3. **`captured_at` 无法由调用方提供**：`CaptureTextRequest` 只有 `text / channel / idempotency_key / user_intent` 四个字段，时间戳由内部时钟注入。这与 README 宣传的"锚定到源位置 + 可审计时间"存在落差，也让幂等重放之外的时间可控性为零。
4. **README 中"25K-line curation-map example"是错误陈述**：`README.md:239`、`README.md:264`、`README-zh.md:239`、`README-zh.md:280` 四处如此宣称，而 `examples/curation-map-example.md` 实测 **326 行**。24,525 是**源文（未收录）**的行数，两者被混淆，把证据基础夸大了约 75 倍。
5. **`archive/v1.0/sop-v1-original.md` 贴错了版本标签**：文件自身第 3 行写 `版本：v2.0（引入粗读器后的全流程修订）`，而 `archive/v1.0/README.md` 与 `CHANGELOG.md` 都称其为"v1.0 完整 SOP 规范原文"。

---

## 1. 项目解剖：它究竟是什么

### 1.1 两个产品装在一个仓库里

| 层 | 内容 | 体量 | 状态 |
|---|---|---|---|
| **A. 捕获内核（软件）** | `src/knowledgeflow_capture/` 15 模块 | 12,202 行 / 473 KB | C0–C6C 完成，C7 CLI 未授权 |
| **B. 策展方法论（提示词）** | `prompts/` 12 文件 + `templates/` | 97 KB | Draft，待重构 |
| **C. 治理层（文档即权威）** | `docs/` 核心规范 10 份 | 545 KB | Approved Design |
| **D. 历史/规划层** | `docs/` 其余 + `archive/` + `examples/` | 509 KB | 多为 Draft / Historical |
| **E. 工具层** | `scripts/` 4 个零依赖脚本 | 65 KB | 可用，但只校验 wiki 页面 |

**关键观察**：A 与 B 之间**没有接口**。捕获内核管理的是 `<capture-root>/items/...` 的二进制事实；策展地图是 `proposals/curation-maps/` 下的 Markdown 散文。前者被 274 项测试锁死，后者零自动化。`proposals/` 目录在仓库中**根本不存在**（已 `glob` 验证），尽管 `design-authority...:233`（C-006）已经冻结了该路径。

### 1.2 治理模型（这是项目最独特的部分）

`docs/design-authority-and-conflict-register-设计权威与冲突登记.md` 建立了：

- **主题级权威**而非文件级：`register:43-44` "一份文档可以在某个主题上继续有效，在另一个主题上被新规范取代"
- **"新设计不等于已实现"**：`Approved Design` 授权实现，但从不声称已交付
- **48 条编号冲突登记 C-001…C-048**（`register:224-275`），每条含 `冲突 / 当前结论 / 状态或门禁`
- **分批停点**：`C3-0`（冻结行为）→ `C3A/B/C`（编码）→ `C3V`（独立验收），每批单独提交、单独授权
- **A0–A5 授权门禁**（`mvp-0-capture-coding-execution-plan...:900-911`），生产初始化需 C8 + 单独显式请求

这套东西对本项目规模而言是**过度设计**，但它确实被执行了：12 份文档对"下一门禁是 C7 受限 CLI（未授权）"的表述完全一致，我逐份核对无矛盾——这在真实项目里罕见。

---

## 2. 工程内核深评（A−）

### 2.1 真正的强项（有代码证据）

**① 不可变事实 vs 派生状态的边界是被强制的，不是命名约定**

- `envelope.yaml` + `events/<evt>.yaml` 写一次即哈希绑定；`capture.yaml` 是唯一可重写文件
- 跨文件引用校验：Event↔Envelope（`codec.py:831-879`）、State↔Envelope/Event（`codec.py:1067-1116`）
- 损坏可检测且可修复，无需触碰不可变历史 —— `recovery.py` 只重建 `capture.yaml`

**② 提交分类基于证据而非异常类型**（这是我见过最成熟的一处设计）

`operations.py:2621-2655` 的 `_classify_append_event_evidence` 与 `:2673-2717` 的 `_classify_commit_exception` 通过探测源/目标 + 内容 attestation 推导出 `committed / not-committed / unknown / integrity-unknown`。**一次"失败"的 rename 如果实际上落地了，会被正确识别为已提交**（`durability.py:604-616`）。

**③ 原子原语默认不覆盖 + 身份复核**

- `"xb"` 排他创建
- `os.rename`（永不 `os.replace`）用于不可变数据；`os.replace` 只用于派生投影（`operations.py:3184`、`recovery.py:509`）
- 每次 unlink/rmdir 前立即复核 `st_dev/st_ino/st_mode` + reparse 标志（`store.py:1568-1617`）

**④ 受限 YAML 编解码器**（`codec.py:585-782`）

手写的 YAML 子集：token 级拒绝 anchors/aliases/tags/directives/merge keys/重复键；标量标签白名单；`ScalarSchema` 用 `type(value) is not self.type` 防御 YAML 1.1 的 `yes/no → bool` 类型混淆；**自研发射器**让字节输出成为 schema 的函数。

**⑤ 故障注入测试是真的**

`_support.py:66` 用 `os._exit(70)` 杀进程，覆盖 **7 个 init 点 + 20 个 capture/append 点 + 3 个 migration 点 + 1 个 rebuild 点 = 31 个故障点**。断言的是磁盘状态而不是 mock 调用：
- `test_capture_faults.py:124-126` 断言崩溃后恰好一个 staging 树含 `transaction.yaml` + `active.lock`
- `:139-143` 断言 staging 回到只剩哨兵文件，且 `sentinel.read_bytes() == b"unknown staging must remain"`
- `:153-159` 断言重试返回**完全相同**的 `capture_id/version/event_id/envelope_sha256`

**⑥ 真实双进程竞争**：`_support.py:306-367` 在真实锁边界同步两个进程；`test_locking.py:153-231` 验证 `terminate()` 后内核锁释放。

**⑦ 零 TODO/FIXME，源码 100% 英文，0 个 CJK 字符**（13,765 行中）——风格高度统一。

### 2.2 实测行为（我亲自跑出来的，不是读代码推断的）

**端到端流程验证**（自建 Store，走真实公开 API）：

```
init_capture_store → InitStoreResult(created=True, store_initialized=True, config_connected=True)
capture_text       → CommittedWriteResult(receipt={capture_id, event_id, version=1,
                       primary_payload_sha256, payload_set_sha256, envelope_sha256, ...})
capture_text 重放  → receipt 完全相同（幂等成立）
list_captures      → ListCapturesResult(items=(...), next_cursor=None)
get_capture        → GetCaptureResult(integrity='verified', body_length_bytes=46) 经 sink 输出
append_capture_version → version=2, previous_version=1, durability='durable'
rebuild_derived_state  → items_scanned=1, versions_verified=2, projections_unchanged=1
```

磁盘结构（init 后）：
```
capture-store.yaml          # 唯一身份文件
items/2026/09/cap_<uuid7>/
    capture.yaml            # 派生投影（唯一可重写）
    events/evt_<uuid7>.yaml # 版本确立 Event
    versions/000001/{envelope.yaml, payloads/primary.txt}
journal/capture-write.lock  # 0 字节内核锁
indexes/idempotency/        # ← 空，从未被读写
outbox/{pending,running,failed,completed}/  # ← 空，从未被读写
```

**错误分类实测**（公开 API 有**两套**失败语义，这是一个可用性问题）：

| 探针 | 结果 |
|---|---|
| stale `expected_current_version` | `FailureResult(VERSION_CONFLICT, details={'current_version': 2, ...})` |
| unknown `capture_id` | **`ValueError` 抛出**（不是 FailureResult） |
| empty text | **`ValueError` 抛出** |
| missing config | `FailureResult(CONFIG_NOT_FOUND)` |
| config 路径越界 | `FailureResult(CONFIG_INVALID)` |
| capture root 在受保护目录内 | `FailureResult(CONFIG_INVALID)` |

**性能实测（这是本报告最重要的量化发现）**：

```
 items  capture_ms  list(page=1)  list(all pages)
    10       248.9         413.3            480.3
    25       451.0        1034.0           1084.9
    50       923.3        2208.4           2096.6
   100      1632.6        3761.1           3740.1
   200      3009.8        7397.6          14759.3
capture_text: mean 1559.6 ms/item over 200 items
```

**线性退化，无索引**。根因：
- `append_capture_version` **总是**扫描并验证整个 Store（`operations.py:3454-3459`、`:2217-2233`）
- 带 `idempotency_key` 的 `capture_text` 扫描每个 item 并对命中项重新哈希（`:3404`、`:1638-1667`）
- `list_captures` 在分页前验证**所有**版本链（`:4106-4134`）
- `indexes/idempotency` 目录被创建但代码从不使用它（`store.py:83` 只声明结构，`recovery.py:252-254` 明确注释"no on-disk idempotency or outbox job"）

**外推**：10,000 条捕获时，单次写入约 150 秒，单次列表约 370 秒。这个设计对"个人知识库日常捕获"是致命的——而 MVP-0 的全部测试都在 ≤200 条 item 的规模下运行，**没有任何规模测试**。

---

## 3. 验证与测试基础设施（B）

### 3.1 实测命令与结果

| 命令 | 退出码 | 结果 |
|---|---|---|
| `python -m unittest discover -s tests -p "test_*.py"` | 0 | `Ran 274 tests in 106.609s` **OK**（需临时目录绕过沙箱 `0o700` 限制） |
| `python -W error::ResourceWarning -m unittest discover ...` | 0 | 274 tests **OK**（子代理验证；严格泄漏门禁通过） |
| `python -m compileall -q src tests scripts` | 0 | 静默通过 |
| `python -m pip check` | 0 | `No broken requirements found.` |
| `python scripts/doc-check.py` | 0 | `38 个现行 Markdown，12 个路由目标，63 个结构树文件` |
| `python scripts/lint.py .` | **2** | `致命错误: wiki/ 目录不存在或不是目录` |
| `python -m pytest -q` | **1** | `No module named pytest`（**故意**：`mvp-0-capture-coding-execution-plan...:159` 规定 MVP-0 只用 `unittest`） |

274 = 259 捕获内核（unit 130 + integration 118 + fault 11）+ 8 文档护栏 + 7 维护脚本。README 的 `tests=274 capture_tests=259 script_tests=15` 锚点**准确**。

### 3.2 测试质量的真实水平

**优秀的部分**：
- 字节级 golden fixture 作为原始字节比较，`.gitattributes` 钉死 LF（12 个 fixture 全部 `CRLF=0`）
- 运行时生成**真实 4 MiB / 64 MiB** 载荷（不是 mock）
- 用插桩 reader/spool 证明 I/O **有界**（`test_list_captures.py:70-90`、`test_get_capture.py:131-152`）
- **公开 API 泄漏护栏**：显式测试故障注入在公开面不可达（`test_init_recovery.py:387,421`、`test_get_capture.py:689`）
- 外部/未知数据保全断言（`test_capture_text.py:582`、`test_init_store.py:544`、`test_recovery.py:74`）

**唯一的浅测试**：`tests/capture/unit/test_smoke.py`（32 行）只断言包可导入与 `__all__` 是超集。其余 33 个模块都在断言行为。

### 3.3 覆盖缺口（按风险排序，全部经验证）

1. **完全没有覆盖率度量**。无 `coverage`、无 `.coveragerc`、无 `[tool.coverage]`。因此 `operations.py`（4,322 行，事务核心）**128 个顶层符号中有 100 个从未在任何测试中被提及**。覆盖率是"不可度量因而不可管理"的状态。
2. **`operations.py` 没有专属单元测试文件**。所有覆盖都是集成级，且**注入依赖**（`_CaptureDependencies`、`id_factory`、`now=`）——真实的默认接线反而被绕过。
3. **`migration.py` 只有 9 个测试方法**（0.74 方法/百行，而 `store.py` 是 8.13），却是爆炸半径最大的操作：移动实时 Store 并原子重写配置。
4. **三个导出的死函数且零测试**：`hashing.verify_envelope_bytes`、`hashing.hash_utf8_text`、`ids.generate_job_id`——在全部 `src/` 中只出现在自己的 `def` 和 `__all__` 里，测试引用 0 次。
5. **真实 ID 生成器被绕过**：`generate_capture_id/event_id/store_id` 是生产默认值（`operations.py:193,198`、`store.py:535`），但因测试注入 `id_factory` 而**命名引用 0 次**。
6. **POSIX 分支从未在任何地方执行**：`durability.py:140 _posix_directory_flusher` 在 `:162` 被选中，测试引用 0 次，CI 仅 Windows。
7. **168/274（61.3%）测试在非 Windows 上硬跳过**（19 个类在 `setUp` 里 `skipTest`）。无 OS 矩阵。
8. **脚本 CLI 缺口**：退出码 1 **从未被断言**；`--quiet` 零引用；`format_report` 零测试引用；`index-generator.py --write` 成功路径未测试。
9. **无属性测试、无 fuzz、无变异测试**——这对 `codec.py` 的 YAML 解析器和 `paths.py` 的 UNC/设备路径解析器是最不适配的。
10. **无 mypy/ruff 门禁**，87 个 mypy 错误被接受为债务。

### 3.4 CI 评价

`.github/workflows/windows-ci.yml`（50 行）：SHA 钉死 actions（带版本注释）、`permissions: contents: read`、`persist-credentials: false`、**严格 `-W error::ResourceWarning` 第二遍全量**、`doc-check.py` 作为真门禁。这些是好实践。

缺口：无覆盖率、无 lint/type 门禁、三个脚本从未以 CLI 形式在 CI 调用、无 OS 矩阵、无重复运行防 flake 检测。

**一个结构脆弱点**：`tests/scripts/test_doc_check.py:119-127` 硬断言 `{"tests":274,"capture_tests":259,"script_tests":15,"next_gate":"C7"}`，这个值同时出现在 6 份文档的锚点里。**加一个测试就要手改 6 份文档，否则 CI 失败。**

---

## 4. 方法论 / 提示词层（D+）—— 项目最大的风险

### 4.1 立论与实现的落差

项目的核心主张（`README.md:47`）：**"LLM 的遗漏比 LLM 的噪声更难修复"**，因此引入策展地图作为审计面，让人能"验证它提取了一切"。整个项目的价值都压在这句话上。

**但覆盖机制的分辨率低于它要检测的失效模式。** 覆盖率规则是"某节 < 0.3×均值 且非盲区 → 偏低"（`prompts/extraction-interface.md:182`、`prompts/sop-001-modeA-auditor.md:65`）。项目数是整数，所以**当均值 ≤ 3.33 时该规则数学上不可能触发**：0.3m ≤ 1，而唯一小于 1 的计数是 0——那已经是"盲区"情形了。样例自己的数据（48 实体 + 21 关系 + 6 主张 = 75 项 / 约 25 个话题）给出均值 ≈ 3.0，正好卡在刀锋上。

**唯一可达的信号是"某节 0 项或 1 项"。这无法区分"30 个概念里提取了 3 个"和"提取了 30 个"。** 而"覆盖内遗漏"与"整类内容系统性遗漏"（如反面案例、限定条件、对冲表述）在构造上不可见。

而且分母本身不稳定：样例 §1 枚举了**恰好 20 个话题**（`curation-map-example.md:19-57`），同一文件却写"跨越 25+ 轮问答"（`:17`）和"覆盖约 25 个独立问答话题"（`:304`）。

### 4.2 硬约束 C1–C7 的漂移登记

| 约束 | 定义处 | 在提示词中的执行点 | 可机械校验？ |
|---|---|---|---|
| C1 绝不创建 wiki 页面 | `README.md:132` | 多处自我声明 | **不可**——由可能违反者自证 |
| C2 每次提取标注源位置 | `README.md:133` | 7 字段表 | **形式上可校验，但无人校验**（无脚本） |
| C3 不确定性显式标注 | `README.md:134` | 置信度字段 | **仅形式**；审计员被禁止检查它（`auditor.md:137`） |
| **C4 Agent 建议与事实结构分离** | `README.md:135` | **提示词层零处** | **不存在执行点** |
| C5 绝不按重要性过滤 | `README.md:136` | 多处 | **不可**，且被 C6 的超长流程自我否定 |
| C6 列出未读章节 | `README.md:137` | 签名块 | **仅形式**，自证 |
| C7 隐式关系标为推测 | `README.md:138` | 多处 | 原则可校验，但**声明的取值不存在** |

**三个必须知道的具体缺陷**：

1. **C4 在提示词层完全丢失**。它唯一被操作化的地方是已废弃的 `docs/sop-v2-full.md:650-663`；对 `prompts/` 目录 grep "Agent 建议" → **0 命中**。这意味着 Agent 自撰的建议可以出现在任何章节（包括 §5.3"选型/决策建议"和 §8），**没有任何隔离标记**。而 `docs/gbrain-integration-plan.md:364` 仍把"Agent 建议隔离"当作提示词标准。
2. **C7 从第一代起就自相矛盾**。"置信度 ≤ 中"（`README.md:138`）引用的取值在声明的枚举 `确定/推测/不确定`（`extraction-interface.md:18`）中**不存在**。三代未修。
3. **C5 与 C6 在长文场景直接冲突**。C5 禁止按重要性过滤，但 `sop-v2-full.md:506` 规定"确认重点章节 → 非重点只概括"，而样例（`curation-map-example.md:312-316`）正是这么做的——用"概念密度低"为跳过 5 个区段辩护，**在 C5 的反对下解决冲突且未声明**。

其他漂移：7 字段被写成 6 列（`不确定原因` 列在 4 个模板中缺失，导致 §6"纯机械聚合"无物可聚合）；§5.3 表头在 4 列/5 列间不一致；`pass2:86` 的示例用了自身 9 类型列表之外的 `implements`；只有 Mode B/C 要求身份头（含 SHA256），**默认模式 Mode A 的产物不带任何哈希**——而 C-009 要求批准必须绑定 `capture_id + version + envelope_sha256`。

### 4.3 覆盖机制的三种实现及其真实强度

**所有 7 个提取/审计提示词都嵌入完整 `{{SOURCE_CONTENT}}`**，`分段/分块/切片/chunk/子地图` 在 `prompts/` 中零命中。所以所谓"2 Pass 分治提取"是**误称**——没有任何分治，只是把同一份源文重读 3–4 遍。

| 模式 | 机制 | 强度 | 静默失效点 |
|---|---|---|---|
| **Mode A**（默认） | 独立审计员对照源文 | 最强 | 审计员被明令"只做结构识别，不读内容细节"（`auditor.md:38`）、不得做语义判断（`:137`）；`全景概括提及` 列被强制填 `—`，关掉了唯一的"提及未提取"信号 |
| **Mode A-fast** | 同一调用自检 | 最弱 | §6.3 要求模型察觉自己忘了什么——正是本项目立论否定的能力 |
| **Mode B** | 3 Pass + 组装 | 弱 | 组装器"不得重读源文"，覆盖表分母**继承自 Pass 1 的概要**；而 Pass 1 已被允许"超过 20 段按节合并"——所以分母本身是提取器的有损产物 |
| **Mode C** | 3 Pass + 组装 | 中 | 组装器重读源文，恢复了源文推导的分母 |

**关键不对称**：B/C 的"交叉校验"很大程度上是**提取器与自身对照**——Pass 2 被明令不得重新提取实体（`pass2:19`），所以它永远无法暴露缺失的实体，共享盲区会读作互相确认。

### 4.4 唯一的样例证明不了任何事

`examples/curation-map-example.md` 的 §10 标题是"覆盖报告（历史缺失声明）"，正文（`:322-324`）：

> "本样例产生时尚未包含现行第 10 节格式，且原始材料未随仓库保留，因此**不能诚实地补造覆盖率、密度异常或盲区数据**"

**整个项目赖以立论的机制，唯一一次被展示时是以"拒绝展示"的形式出现的。** 这个缺陷项目自己的审计清单早已记录（`docs/improvement-action-plan.md:150`，审计项 7 / P0-5）。

内容的公允评价：**不是编造的**。`@fact:harness-langchain-30-to-5`（`:209`）与 LangChain 自身公开声明一致；Can.ac 的 "6.7% → 68.3%"（`:208`）是中文技术博客生态中的真实二手数据，且都被正确标为 `推测/来源不可靠`。但它是**按形状手工组装的**：80 个标识符各出现恰好一次（从不复用），因此 18 条显式关系中有 15 条的端点匹配不到任何已定义实体，违反 `extraction-interface.md:68/70`；§8 声称 SCHEMA 有"6 种页面类型 + 9 种关系类型"却列出 4 种页面类型和 6 种关系类型；`:267` 说现有集合"足以覆盖本原料全部显式关系"而 `:276` 又把其中四种列为未收录。

**它无法作为回归 fixture**——没有任何机器可校验的不变量。

### 4.5 修复方向（这是本报告最有价值的一条建议）

把分段与覆盖记账**从 LLM 手里拿走**：

1. 用**已经存在的**捕获内核把源文摄入（哈希、原子写、版本），确定性地切成**编号且字节锚定**的段落
2. 要求每段产出一条记录：要么 ≥1 条带 `segment_id + span` 的提取，要么一条带原因码的"无可提取内容"豁免
3. §10 由脚本从（段落 × 提取记录）**计算**得出——每段计数、盲区、密度都变成派生事实
4. 于是 C2、C5、C6 变成**可机械校验**（每段都有交代、span 能解析到字节、无静默跳过）
5. 覆盖报告不再是"生成的章节"，而是 join 的输出——**它不可能缺失，也不可能美化**
6. 人审变成审阅异常清单，而不是 300 行表格
7. 顺带解决：消除未定义的章节编号 join；让密度阈值有意义（零提取段落，而非无法触发的 0.3×均值）；默认路径可以减一次 LLM 调用；长文改为分片而非重读；给未来的写入器提供 C-009 已经要求、但当前地图格式无法表达的机器可消费变更集

**项目已经造好了这套所需的每一个原语——只是把它们瞄准了写入路径，而不是瞄准整个立论所依赖的那个产物。**

---

## 5. 文档与治理层（B−）

### 5.1 体量对比（实测）

| 度量 | 数值 |
|---|---|
| 全部已跟踪 Markdown | **1,126,067 B / 44 文件** |
| `src/*.py` | 473,132 B / 12,202 行 / 15 模块 |
| `tests/` | 461,719 B / 10,981 行 |
| Markdown : src | **2.38 : 1** |
| 核心治理 : (src + tests) | 0.58 : 1 |

**公允判断**：标题比率被两件事放大——(i) `prompts/`+`sop-v2-full`+`archive` 是**另一个产品**（509 KB，占全部 Markdown 的 45%）；(ii) 中文内容的字节膨胀约 2–3×。针对治理层实际治理的对象，0.58:1 是温和的。而且 221 条测试矩阵（`mvp-0-capture-implementation-plan...:627-847`，CT/GET/LIST/APP/INIT/REC/MIG 等 12 个 ID 族）不是仪式——我验证了套件确实收集 274 项且拆分吻合，**矩阵与代码是相互对应的**。

**但确有冗余**：
- `gbrain-integration-plan.md` = 53,152 B，而 register `:76-77` 把该集成降级为**两行可选 POC**
- `improvement-action-plan.md` = 34,582 B 讲 14 个任务，每个任务**写了四遍**（问题+步骤 / 依赖图 / 验收表 / 附录），且 **14 行验收中 13 行仍未勾选**
- `archive/v1.0/sop-v1-original.md` = 80,458 B，与 `docs/sop-v2-full.md` **约 95% 重复**
- 摄入管线图在 register §6 + `build-plan.md` + `second-brain-vision.md` + `gbrain-integration-plan.md` **四份文档中各画一遍**
- `post-c3-...md:699` 明文要求"不删除 golden fixtures、测试、`.eval-tmp`、`tmp-eval` 或空 `assets/`"——所以空 `assets/`、空的 `docs/ui/` 都按策略保留

### 5.2 已确认的具体缺陷

**高严重度**
1. `archive/v1.0/sop-v1-original.md` 是 v2.0 文档却被标为 v1.0；`archive/v1.0/README.md:13-14` 描述的"v1.0 局限"（提取与策展合并、无人类审查面）**恰好是该文件已经修复的东西**；`:26` 称其含 SOP-000…SOP-005 而文件里有 SOP-006（`:1655`）
2. **双语 README 不平行**：`README-zh.md:262` 有完整的 `## 不确定性处理` 章节 + 5 行表格 + `:19` 的路由行，**英文 README 完全没有**（英文 9 个 H2，中文 10 个——我已逐行核对）。而 CI 绿灯，因为 `scripts/doc-check.py:191-192` 丢弃纯 `#anchor` 目标、`:348-367` 只比较路由目标**集合**和结构树**文件集合**，从不检查标题或章节数。项目自己的审计已记录该缺口（`improvement-action-plan.md:202`）
3. `README.md:239,264` + `README-zh.md:239,280`：把 326 行的文件称为"25K-line"

**中严重度**

4. `capture-envelope-v1...:1010` 要求崩溃注入"在 T4 至 T10 每个阶段"，但事务只定义到 T9（`:672-681`），**T10 不存在**
5. **两份规范性文档的验收清单完全未勾选**：`capture-envelope-v1` §18 有 26 个 `- [ ]` / 0 个 `[x]`；`capture-and-routing-spec` §21 有 15 个 / 0 个。全仓库 84 未勾选 vs 19 已勾选
6. **`config_store_conflict` 是公开错误码却没有公开错误表条目**：定义在 `errors.py:26`，在实现计划中被指定 8 次，但**缺席**`mvp-0-capture-operations...:630-647`——而 `capture-envelope-v1:973` 明确声明该表是公开错误码的权威
7. `requirements-and-governance-baseline...:346,347` 两行都编号 `6.`
8. `mvp-0-capture-coding-execution-plan...:148` 列出 `tests/capture/migration/`，该目录不存在且**无状态说明**（迁移测试在 `integration/test_store_migration.py`）
9. **README 结构树只列 1 个 research 子目录**（`README.md:212`），实际有 3 个（09-11/09-13/09-14）；护栏只检查"列出的存在"，从不检查完整性
10. **`C7` 在全仓库有歧义**：在 `curation-paradox.md:3`、`sop-v2-full.md:466`、`improvement-action-plan.md:165,407` 指 SOP-001 硬约束 #7，在其他所有地方指编码批次 C7（受限 CLI）。而机器锚点里写的就是 `next_gate=C7`
11. **最关键的路径元素没有定义**：Item 目录名在文档中**7 处**都是占位符 `<capture-id>`，而 `mvp-0-capture-operations...:238` 要求把目录名与 `capture_id` 比较。**哈希原像的字节序钉到字符级，而布局中最吃重的路径元素留作占位符。**
12. **`sop-v2-full.md` 在 12 处仍教被禁止的路径** `raw/_curation-maps/`，只有 1 处（`:408-411`）给出更正；而 C-006 已冻结为 `proposals/curation-maps/`
13. **暂停标记只加在 8 个模板中的 3 个**上；**12 个提示词文件中有 8 个仍把部分废弃的旧 SOP 称为"完整 SOP 规范"**且无任何警示。被暂停的 `sop-002-curator.md` 主体仍完全可执行，仍内联着被禁止的自动变更（`:96-101` 自动注册标签、`:283-284` 自动执行 SOP-004），**唯一护栏是顶部一条横幅**
14. **`sop-000a` 与 `capture-envelope-v1` 同挂 `Approved Design` 标签，严格度天差地别**：后者把哈希原像钉到字节；前者自述 `kb.yaml` 是"建议的最小草案"、":字段和枚举需在实现前另行定版"，且其 11 项验收**全部未勾选**
15. **"单一冲突登记"实际是五个互不交叉引用的登记册**：register §9（48 条，有 ID）+ `requirements` §14（7 条，无 ID）+ `routing` §22（7 条，无 ID）+ `sop-000a` §13（6 条）+ `improvement-action-plan`（25 条），另有 gbrain 6 条 + QQ 4 条开放问题。只有 register 那份带 `C-xxx` ID，而全仓库引用的正是它

### 5.3 研究层（做得意外地好）

`docs/research/` 的四个文件是**AI agent 的评审记录**，非人类评审。索引页的规则写得极准：`:8` "不是项目指令、用户授权、现行契约或完成证明……均对应形成时的仓库快照"，`:37` "命令式措辞只表示建议，不构成执行授权"，`:40` "应新增复核记录，不静默改写这些历史输入"。

**哈希已由我复算，四个全部匹配**；`.gitattributes` 用 `-text whitespace=-trailing-space` 保真；`doc-check.py:412-448` 强制每个已跟踪研究正文都被索引列出。

**但规则只写在文件之外**：四个日期文件正文里 grep `非权威|Historical` 只命中索引和一处引用；`20260911.md:173` 读起来就是一份可执行的规范性计划（"### R0.1 ... **单独提交**："）。内容确实已陈旧（`:7` "13 模块，物理行 6,802" → 现为 15 模块 / 13,765 行），而这恰好证明该规则是承重的而非装饰性的。

**层内自相矛盾**：`0913dsh.md:51-61` 声称六个锚点让文档漂移"结构上不可能复发"，**而同一文件 `:58` 就带着一个竞争的锚点**（`tests=163 ... next_gate=C4A`），`tests/scripts/test_doc_check.py:16` 还有第三个（`tests=156 ... next_gate=C4-0`）。全仓库 grep 锚点字符串返回**三个互相矛盾的事实**。

---

## 6. 缺陷总清单（按严重度排序）

### S1 — 影响正确性或立论

| # | 缺陷 | 证据 | 影响 |
|---|---|---|---|
| 1 | **"durable" 声明在 Windows 上不成立** | `durability.py:159-162` 在 `nt` 上返回 `None` → `flush_directory_metadata` 恒返回 `UNSUPPORTED`（`:303-304`）；**~34 处调用点（durability 10 / store 11 / operations 5 / migration 4 / recovery 3）没有任何一处检查返回值**；而回执与投影却写 `durability: "durable"`（`operations.py:1708,2322,3087`、`recovery.py:303`） | 文件内容 fsync 了，但让它们可达的 mkdir/rename **目录项从未落盘**。NTFS 日志通常掩盖这一点，但代码既不验证也不报告 |
| 2 | **迁移中断⇒永久不可重试的残缺目标** | `migration.py:563` `destination.open("xb")` **直接写最终路径，没有 tmp+rename**；中途被杀留下短文件，此后每次重试都走不匹配→`UNRECOGNIZED_EXISTING_DIRECTORY`（`:645-667`、`:1129-1133`），只能手工删除；唯一的迁移故障点 `AFTER_TARGET_FILE_COPIED`（`:673-676`）在**完整文件写完之后**触发，所以这个窗口**在构造上未被测试** | 更糟的是：所有目录先建（`:626-637`）且文件按排序复制，`capture-store.yaml` 排最前，所以目标在**复制完第一个文件后就能通过 `_inspect_store`**，且 store_id 相同——没有 `.incomplete` 意图标记 |
| 3 | **提交后的锁释放失败会把成功的迁移报成失败** | `completed` 在目标锁体内赋值（`migration.py:1060`），但那是**与 `_run_migrate_capture_store`（`:1086`）中不同的局部变量**，后者只在 `_migrate_locked` **返回**时（`:1105`）才绑定。若目标锁 `__exit__` 抛 `CaptureWriteLockError`，外层 `completed` 仍为 `None`，`:1114` 的守卫无法触发 → 调用方拿到 `capture_store_unavailable` / `stage="migration-lock"` / `retryable=False`，**而配置已经切换、迁移已提交**。同时 `:1072-1073` 的防御性 `if completed is None: raise` **不可达** | 操作者会认为迁移失败并可能执行错误的补救动作 |
| 4 | **覆盖检测器的分辨率低于它要检测的失效** | 0.3×均值规则在均值 ≤3.33 时数学上不可触发（`extraction-interface.md:182`、`auditor.md:65`）；样例自身均值 ≈3.0 | 可检测的只有"整节 0 项或 1 项"；节内遗漏与整类内容遗漏在构造上不可见 |
| 5 | **没有任何机制确立"模型究竟读到了什么"** | 所有 7 个提取/审计提示词嵌入完整 `{{SOURCE_CONTENT}}`；`分段/分块/切片/chunk` 在 `prompts/` 零命中；唯一样例声称 ~16.7 万 token 源文，唯一让步是"列出没细读的部分"（`modeA.md:272`） | C5 的保证与 §10 的仪器都预设了忠实完整的摄入，而提示词层不提供任何保证 |

### S2 — 影响可用性/可扩展性

| # | 缺陷 | 证据 | 影响 |
|---|---|---|---|
| 6 | **热路径 O(Store)，无索引可用** | 实测 200 条时 `capture_text` 均值 **1560 ms**、`list_captures(limit=1)` **7.4 s**；`operations.py:3454-3459` append 全量扫描、`:3404`/`:1638-1667` 幂等全量扫描、`:4106-4134` 列表全量验证链；`indexes/idempotency` 被创建但零读写（`recovery.py:252-254` 明确注释） | 个人知识库日常使用场景下致命；无任何规模测试覆盖 |
| 7 | **没有任何 CLI；端到端流程不可执行** | `src/knowledgeflow_capture/cli.py` 不存在；无 `[project.scripts]`；四个操作全部要求显式传入 `PathPolicy`（**无默认值**）；`init_capture_store`、`migrate_capture_store`、`rebuild_capture_store_derived_state` **都不在 `__init__.py` 的 `__all__` 里** | 用户无法只靠这个包做任何事；只有测试能驱动它 |
| 8 | **公开 API 有两套失败语义** | 实测：`empty text` 与 `unknown capture_id` 抛 `ValueError`；而 `stale version` / `missing config` 返回 `FailureResult` | 调用方必须同时写 `try/except` 和检查返回值，容易漏 |
| 9 | **`captured_at` 调用方不可控** | `CaptureTextRequest` 只有 4 个字段（`text/channel/idempotency_key/user_intent`）；时间戳来自 `operations.py:171` 的内部时钟 | 无法回填历史捕获、无法测试确定性、无法导入 |
| 10 | **`fidelity` 在 schema 层可扩展但读路径钉死** | `codec.py:242-252` 允许 `byte-exact/channel-exact/canonical-snapshot/reference-only`；`operations.py:1093-1104` 要求恰为 `channel-exact`，否则报 `PAYLOAD_SET_HASH_MISMATCH` | 一个 schema 合法的 envelope 会被报成"载荷集哈希不匹配"——错误分类学缺口 |
| 11 | **崩溃窗口产生永久孤儿** | `.staging/<uuid>` 若在 marker 落盘前崩溃（`store.py:1135-1186`），恢复**故意拒绝**处理无有效 marker 的树（`:1759-1774`），该目录**永不被回收**；`.capture-state-*.tmp` 写在 item 根目录（`operations.py:3152-3153`），而没有任何 reader 或 rebuild 会枚举 item 根目录 | `.staging` 可单调增长；孤儿还会让后续迁移失败（`migration.py:679` 的精确快照断言） |

### S3 — 工程质量/可维护性

| # | 缺陷 | 证据 |
|---|---|---|
| 12 | **大规模跨模块重复，存在真实的发散风险** | `_is_reparse_point` ×4、`_lstat_if_present` ×5、`_same_identity`/`_failure`/`_path_key` 各 ×3、`_noop_fault_hook`/`_trigger_fault` 各 ×4；锁类三份逐字节重复（`locking.py:62-214`，约 150 行）；capture/append staging 校验与清理近乎重复（`store.py:1338-1702`，约 350 行）；两个写入循环只有一个校验短写边界（`durability.py:246-252` vs `:363-368`） |
| 13 | **过宽的 `except Exception` 掩盖事实** | `operations.py:3014-3023` 把**空操作故障钩子**包在 `try/except → NOT_COMMITTED` 里；`:3188-3189`/`:3263-3264` 把**任何**异常降级为"投影需重建"警告；`:1612-1613` sink 异常 → `OUTPUT_WRITE_FAILED`；`:1236-1241` spool 写失败**丢弃 cause**（`exc` 未使用、无 `from exc`）；`migration.py:914-925` 把 `os.replace` **和随后的目录 flush 和故障钩子**包在同一个 `except` 里——若 replace 成功而 flush 抛错，函数读回校验通过并**返回成功**，静默吞掉 flush 失败 |
| 14 | **每个文档加载 = 3 次解析 + 1 次全量重发射** | `codec.py:646`(scan) + `:649`(compose) + `:660`(load)，`require_canonical=True` 再加 `:793` 的重新发射+字节比较。每个 item 读 envelope + event（list/rebuild 还要读投影），全部走 `require_canonical=True` |
| 15 | **写放大严重** | 每次持久写后全量字节比较回读（`durability.py:321-327,385`）；文本载荷再**第二次**全量回读重算摘要与 UTF-8 有效性（`:388-438,509-520`）；`commit_file_no_replace` 校验源和目标的**两者**（`:586,618`） |
| 16 | **严格性在目录之间不一致** | `outbox/` 或 `indexes/*` 下的任何意外条目会以 `UNSUPPORTED_STORE_VERSION` **中止整个 rebuild**（`recovery.py:242-254`）；而 `items/` 下不符合 `cap_` 前缀的条目被**静默忽略**（`operations.py:942,956,970`） |
| 17 | **可靠性/原因传递在迁移中形同虚设** | `grep 'retryable=True' migration.py` → **0 命中**：全部约 37 处 `_MigrationIoFailure` 都用默认 `retryable=False`，所以 `:1150` 的 `retryable=exc.retryable` 是常量 `False`——真正瞬时性的失败（复制写、fsync、目标竞争）被报为不可重试。`_MigrationIoFailure` **没有 `cause_code` 字段**，底层 `OSError`（磁盘满、拒绝访问）被丢弃 |
| 18 | **已证明的死代码/不可达守卫** | `locking.py:318 _capture_write_lock_path` 全仓库无调用者；`migration.py:144-145` 与 `recovery.py:140-141` 的 `init=False` 不变量**永不触发**；`migration.py:986,1072` 与 `recovery.py:649` 的守卫不可达；`migration.py:389-393 _digest_file` 恒返回 `relative_parts=()` 占位；`hashing.verify_envelope_bytes`/`hash_utf8_text`、`ids.generate_job_id`/`extract_unix_ts_ms`、`IdKind.JOB` 无包内调用者；`CauseCode.projection_update_failed`/`outbox_projection_failed`、`WarningCode.outbox_needs_rebuild` 是不可达词汇 |
| 19 | **迁移对目标树全量哈希 4 次** | `migration.py:1027`（锁前）+ `:1035`（目标锁内）+ `:623`（`_copy_snapshot` 内，**中间无任何目标写入**）+ `:678`；每个复制文件被哈希 4 次；`_StoreSnapshot.files_by_path` 是每次访问都重建 dict 的 `@property`（`:181-183`），被 3 个调用点访问 |
| 20 | **`_cleanup_transaction_candidates` 每次 init 都物化整个父目录** | `store.py:2131` `tuple(request.capture_root.parent.iterdir())` 与 `:2219` 配置目录。若 capture root 位于下载目录或仓库根目录，这是一次大扫描 |
| 21 | **魔法数字分散** | 版本上限 `999999` 写在 4 个模块（`models.py:21`、`codec.py:444,547`、`errors.py:213`）；`store.py:2167` 用硬编码 `len(value) != 101 or value[64] != "-"` 校验配置临时文件名；`_freeze_receipt` 硬编码 `version == 1` 与 `"unreviewed-capture"`（`errors.py:179-187`） |

---

## 7. 值得称赞的地方（不该被上面的缺陷掩盖）

1. **提交分类基于证据**（`operations.py:2621-2717`）——这是整个代码库最成熟的一处设计，值得作为范本。
2. **不可变/派生的边界是被强制的**，不是命名约定。
3. **31 个真实进程崩溃注入点**，断言磁盘字节而非 mock。
4. **公开 API 泄漏护栏**（`test_init_recovery.py:387,421`）——显式测试故障注入在生产面不可达。
5. **路径策略的深度**：拒绝设备命名空间、UNC、`..`、受保护根、KB 祖先标记（`paths.py:26-50,161-204`）；测试所有权是**注入的对象能力**，明确不可由 YAML 表示（`:96-100`）。
6. **错误诊断不可泄漏**：失败 `details` 被限制在类型化白名单（`errors.py:119-133`），路径/载荷/异常文本无法进入公开错误。
7. **不可伪造的类型化回执**：精确键集校验 + 逐字段域校验 + `MappingProxyType`，且**拒绝把已提交的写表示为失败**（`errors.py:162-232,369-370`）。
8. **TOCTOU 在锁边界重新校验**：`_prepare_request` 在取锁前后各跑一次且必须匹配（`store.py:2463-2484`）；写入者在取得 Store 锁后重新读配置（`operations.py:3364-3387`）——**显式拒绝掉队写入者**。
9. **有界 I/O 到处都有**：用 `+1` 探测读而非信任 `st_size`（`durability.py:203`、`operations.py:555-608`、`hashing.py:84-94`）。
10. **研究层诚实**：日期快照、记录 SHA-256（我已复算全部匹配）、`.gitattributes` 字节保真、索引 allowlist 强制。
11. **交付声明可验证**：CI run `35319645501` 我通过公开 API 确认 `conclusion: success`、`run_attempt: 1`、`head_sha: ea8f84e...`；六个批次提交都存在且是 HEAD 祖先；生产路径确实不存在。**这个规模的项目很少做出这么可核查的声明，而且它们经得起核查。**
12. **"下一门禁"在 12 份文档中表述完全一致**，无竞争叙事。
13. **缺陷的自我记录**：`improvement-action-plan.md` 和 `docs/research/` 记录了大量本报告的同类发现（P0-5 覆盖报告缺失、双语标题结构未实现、Mode A 测量从未执行）。**项目对自己问题的诚实度高于绝大多数项目。**

---

## 8. 优先级建议

### P0 — 在做任何新功能之前

1. **修 `archive/v1.0/` 的版本标签**，并修正两份 README 的 "25K-line" 陈述（4 处）。成本 10 分钟，收益是恢复"可验证声明"姿态的可信度——这是项目最珍惜的资产。
2. **修双语 README 不平行**：要么补上英文的 `## How uncertainty is handled` 章节，要么删除中文的。同时**修 `doc-check.py` 让它比较标题集合**（`:348-367` 现在只比较路由目标集合与结构树文件集合）。项目自己的审计已记录此缺口。
3. **修 `migration.py` 的两个真实缺陷**：`:563` 改为 tmp+rename（否则中断即不可恢复）；`:1060` 的 `completed` 赋值作用域（否则成功的迁移被报为失败）。
4. **让 `durability` 声明诚实**：目录 fsync 在 Windows 上不可用是**可以接受的工程现实**，但回执不该无条件写 `"durable"`。要么在 `DirectoryFlushStatus.UNSUPPORTED` 时降级该字段或产出 warning，要么在文档中明确"durable 仅指文件内容"。

### P1 — 决定项目是否成立

5. **给策展地图加机器可校验的契约**。当前它：没有解析器、没有 fixture、没有 CI、没有脚本知道"策展地图"这个词（我对 `scripts/*.py` grep `策展|curation|标识符|覆盖报告|@concept|@rel:` → **零命中**），而唯一的样例 §10 拒绝产出覆盖数据。没有这一步，项目的核心主张**无法被证伪也无法被证实**。
6. **执行 §4.5 的分段+记账重构**：用已存在的捕获内核做确定性分段，覆盖报告由脚本计算而非 LLM 生成。这是把 C2/C5/C6 从"愿望"变成"可检查"的唯一路径。
7. **清理提示词层的约束漂移**：恢复 C4 的隔离章节（或明确废弃它）；修 C7 的"≤ 中"取值；把 7 字段/6 列的表头统一；给 Mode A 加身份头（含 SHA256），否则它无法满足 C-009 的批准绑定要求。注意 `modeA-fast.md:34-282` 与 `modeA.md` **99.2% 逐字重复**（249 行），所以每个字段级修正都要做两遍——先合并，再修。

### P2 — 让它可用

8. **做 C7 受限 CLI**（已规划、未授权）。目前**用户无法使用这个软件**。同时给四个操作提供 `PathPolicy` 的默认构造，或提供明确的公共工厂。
9. **测规模，然后决定**。当前 200 条时单次写 1.56 秒。要么实现 `indexes/idempotency`（目录已存在、结构已声明、只差逻辑），要么在文档中明确容量上限并加一个规模回归测试。
10. **统一失败语义**：让所有可预期失败都返回 `FailureResult`（含错误码），`ValueError` 只留给编程错误。当前的混合模式让调用方必然写错。

### P3 — 工程卫生

11. 引入覆盖率度量（哪怕只是 `trace` 模块）。`operations.py` 128 个顶层符号中 100 个从未被测试命名——这是**无法管理**的状态。
12. 消除跨模块重复：抽出共享的 `_is_reparse_point`/`_lstat_if_present`/`_same_identity`/故障钩子，以及三份重复的锁类和约 350 行的 staging 辅助函数。
13. 清理不可达代码与不可达守卫（第 18 条），或为它们写测试并说明用途。
14. 给 `pyproject.toml` 加 `[project.optional-dependencies]` dev extra——目前开发工具链**无法从仓库复现**（这也是 `pytest` 缺失的结构性原因）。
15. 把 6 份文档里的测试数硬编码改成从套件派生，消除"加一个测试要改 6 个文件"的脆弱耦合。

---

## 9. 结论

**这个项目有两种可能的未来。**

一种是：**它继续是一个优秀的工程作品，但立论失败。** 捕获内核会被继续加固（C7、C8、更多批次），测试数会从 274 涨到 400，文档会继续同步；而策展地图依然没有解析器，覆盖报告依然由被审计方自己生成，密度规则依然数学上不可触发，"遗漏可检测"这个承诺依然只在"整节为零"这个粒度上成立——**而这恰好是长文、陌生领域、LLM 注意力衰减时最不可能出现的失效形态**。届时项目会拥有一台极其可靠的机器，用来保存和审计一个不提供其核心保证的产物。

另一种是：**项目意识到它已经造好了答案所需的全部零件。** 捕获内核有哈希、原子写、版本链、崩溃恢复；它缺的只是把确定性分段和覆盖记账接上去，让覆盖报告成为 join 的输出而不是 LLM 的章节。这条路的每一步都不需要新原语，只需要把已有的原语从"写入路径"调转方向，对准**整个立论唯一依赖的那个产物**。

**从工程证据看，这个团队有能力走第二条路。** 31 个崩溃注入点、证据式提交分类、抗 TOCTOU 的锁边界重校验、对自身缺陷的诚实记录——这些都表明团队理解"可验证性"的真正含义。它只是还没有把这种理解应用到最需要它的地方。

---

### 附：本次评估的方法学声明

- **未修改任何项目文件**（`git diff HEAD -- src tests scripts .github pyproject.toml` 为空）。所有实测均在 `.agent-tmp/` 临时目录内进行。
- 测试套件在本沙箱中的首次运行报 274 项失败，根因为沙箱对 `os.mkdir(path, 0o700)` 的权限策略与 `tempfile.mkdtemp` 的硬编码 `0o700` 冲突。**这不是项目缺陷**：修正后 `Ran 274 tests ... OK`，严格 `ResourceWarning` 模式同样 OK，与远端 CI run `35319645501` 的结论一致。
- 遗留的 `.agent-tmp/`（本报告工作目录）、`.probe-new/`、`tmpu5uxhkuy/` 为评估过程产生的未跟踪临时目录，沙箱拒绝删除其中 `0o700` 权限的子目录；三者均不在 git 索引内，不影响仓库状态。
- 报告中标注为"实测"的数据均由本次评估直接运行产生；标注 `文件:行` 的结论均由阅读源码/文档确认。
