# Changelog

---

## Unreleased

### 治理式捕获架构、C3 验收与 R0 初始化加固

- **建立主题级设计权威**：新增需求与治理基线、设计权威与冲突登记、SOP-000A、捕获与路由规范、Capture Envelope v1、MVP-0 四操作契约、实现拆解与编码执行方案。
- **冻结语义写入边界**：捕获允许先保存后审核；模型只生成路由或策展提案；旧 SOP-002 及其写入提示词暂停执行，策展地图迁移到 `proposals/curation-maps/`。
- **完成 C0–C2**：新增内部 `knowledgeflow-capture` Python 包，实现结构化错误与三态提交状态、UUIDv7、Payload/Payload Set/Request Fingerprint/Envelope 四类哈希、受限 YAML 语法门禁/schema 校验/确定性发射、本地配置、Windows 路径策略、Store Manifest v1、初始化内核锁、durability 原语及安全 Store 初始化。
- **闭合初始化恢复边界**：实现幂等重开、无覆盖配置连接、同请求/异 root 多进程竞争、保守事务残片归属，以及六个仅内部可选的初始化故障点和跨进程崩溃恢复验证；不宣称突然断电安全。
- **建立可复现验证**：C0–C2 里程碑形成 85 项自动化测试和五份 JSON/YAML golden fixture；严格 `ResourceWarning`、`compileall`、依赖完整性和 diff 检查均通过。golden 文件固定使用 LF，避免 Windows checkout 改变契约字节。
- **清理仓库临时产物**：删除误提交的 `.eval-tmp` 合成数据，补充本地环境、构建产物和实验目录忽略规则。
- **明确进入 C3 前的未交付范围**：该时点四个文本操作、Capture Item/版本事务、State Event 业务持久化、幂等索引、生产 Store、人工路由、GBrain、Harness、UI 和可信知识写入均未实现；后续条目逐批记录其中 `capture_text` 的实现进展。
- **冻结 C3-0 行为边界**：确认文本/流输入、完整 Item + `capture.created` 原子提交、初始投影、Store 级写锁、幂等身份及 actor/UTC 规则；该设计确认当时未授权或实现 C3。
- **完成 C3 前稳定化**：公共错误诊断和成功回执改为类型化字段白名单；三个维护脚本对无效 KB 与重复 basename 失败关闭，`index-generator --write` 不再在失败时覆盖 index，Wikilink 验证排除行内代码；新增 1 项错误模型和 7 项脚本回归测试，全量测试增至 93 项。
- **完成 C3 编码前契约收口**：统一 C3 成功回执并移除冗余 `payload_count`，固定完整性错误消息，明确幂等重试保持不可变身份/版本/哈希而警告反映当前投影事实，统一可选意图的省略归一化和新 ID 目标碰撞结果，移除捕获规范中的旧 `capture.yaml` 伪格式；该收口完成时尚未授权或实现 `capture_text`。
- **固化 C3 分批停点**：将 `capture_text` 拆为独立授权、复核和提交的 C3A 契约能力、C3B 写入基础、C3C 完整事务与 C3V 验收四批；测试随批次增量交付，最终按 CT-01–CT-24、真实 4/64 MiB 和 Windows 多进程边界验收；拆分确认时尚未授权任何 C3 编码。
- **完成 C3A 契约能力**：提交 `346164d` 实现严格 Event/Projection v1、渠道与时间边界、规范幂等 scope/key 摘要、精确成功回执及 golden fixture；普通与严格 `ResourceWarning` 全量测试均为 105 项，未创建 staging 或公开 `capture_text`。
- **完成 C3B 写入基础**：提交 `8050d88` 复用 Windows 内核字节锁形成固定 Store 写锁，实现单遍有界 UTF-8 写入、落盘回读复算、T0 staging 所有权与固定树安全清理；普通与严格 `ResourceWarning` 全量测试均为 122 项，仍未扫描正式 Item、写 `capture.yaml` 或公开 `capture_text`。
- **完成 C3C 完整事务**：公开 `capture_text`，闭合 T0–T9 的配置/Store 检查、有界 Payload、幂等扫描、Store 锁、Envelope/Event 封存、完整 Item 无覆盖提交、最终回读、初始投影与结构化回执；缩小阈值下覆盖 CT-01–CT-24 核心分支及 Windows 双进程同 key、目标冲突、提交前 Event 故障、提交后投影故障和 rename 三态证据，普通与严格 `ResourceWarning` 全量测试均增至 140 项。
- **完成 C3V 独立验收**：提交 `00e8e3a` 增加运行时生成的真实 4 MiB/64 MiB 边界、有界非 seekable 输入、锁边界双进程同 key 竞争、默认 10 秒写锁超时及加强版故障磁盘证据；普通与严格 `ResourceWarning` 全量测试均为 144 项。该数字是 C3V 历史里程碑，不是当前总数。
- **完成 R0 初始化所有权加固**：R0.1 提交 `92a37b3` 将自有初始化事务的 marker 固定为最后删除，并验证清理中断后的跨进程恢复；R0.2 提交 `79515ed` 以完整请求哈希和事务 UUID 命名配置临时文件，只清理身份与规范字节均匹配的候选。两批完成时，普通与严格 `ResourceWarning` 全量测试均为 148 项（捕获内核 141 项、维护脚本 7 项）。
- **完成 D0/D0-F 文档事实收口**：当前活跃调用数统一为 A=2、A-fast=1、B=3、C=4；Mode B 保留并填写第 7/8 节但明确不重读源文；历史样例补充不可复原的第 10 节声明并移除旧 SOP-002 执行指令；实践数据改为可审计口径。D0 补齐 C3-0 与 C3 后方案入口，修正提取接口章节引用、阈值用途和历史验证证据措辞；D0-F 把综合方案纳入项目文档，把两份复核文本归档为非权威研究输入，并闭合 README 路由、Git 跟踪意图与状态记录。下一批是单独授权的 D0G 最小文档护栏，之后才进入另行授权的 C4-0。
- **建立 D0G 最小文档护栏**：新增零第三方依赖的 `doc-check.py`，以 Git 索引核对双语 README 路由/结构树、现行 Markdown 相对链接、`docs/` 未跟踪文件、历史研究 allowlist 和六份机器可读状态锚点；新增 8 项回归后全量为 156 项。本批已由独立本地提交闭合，未执行 push；下一门禁 C4-0 未获授权。
- **完成 C4-0 读取契约收口**：冻结由唯一版本建立 Event 证明的连续可见版本链，新增 `capture.version-appended` 对前后 Envelope 哈希的绑定并把 Event 定为追加逻辑提交点；`get_capture` 固定为全量验证后经有界磁盘 spool 向调用方 sink 输出，`list_captures` 固定为结构/Event/Envelope/大小校验和有界 160 code point 预览；同时冻结 Store/查询绑定的 `c1` keyset 游标、严格时间边界、静态数据集分页保证及可归属 warning，解决 C-027–C-031。未修改生产代码、测试、fixture 或提示词，未创建生产 Store；本批由独立本地提交闭合，未执行 push，下一门禁 R0.3D 尚未授权。
- **完成 R0.3D 初始化错误语义诊断与裁决**：新增 3 项只使用测试临时目录的特征测试，确认 M1 并非整段死代码，但未知初始化候选的 `stat` 失败会阻断幂等重开；确认 M3 的二次清理身份失败会遮蔽原始 `file-readback` 阶段；确认 M4 当前只缺 WinError 32/33 的可重试分类，WinError 5 与仅 `errno.EACCES` 必须保持不可重试。C-032–C-034 已冻结 R0.3F 的修复边界；本批不修改生产代码，当前全量增至 159 项，并已通过独立本地提交闭合、未执行 push，且不自动授权 R0.3F 或 C4A。
- **完成 R0.3F 初始化错误语义修复**：未知事务候选在 marker/request 归属证明前发生 `stat` 失败时保守跳过且不删除，归属证明后的遍历、身份复核与删除错误继续失败关闭；Store 与配置两条清理路径均保留首个公共错误，只以安全 `details.cleanup_stage` 记录次级清理阶段；durability 默认不可重试且仅直接 WinError 32/33 为可重试。3 项 R0.3D 特征测试已转换为目标回归，并补充 marker stat、自有树 stat、配置清理优先级和诊断字段安全测试；当时全量增至 163 项，本批已通过独立本地提交闭合，未执行 push，也不自动授权 C4A。
- **完成 C4A 读取侧契约能力**：新增严格 `capture.version-appended` Event 分支及前后 Envelope 引用校验、读取请求/结果模型、精确 warning/输出错误形状、Event 证明的连续版本链与唯一无 Event 尾部纯原语、只读内存状态、规范查询指纹和 `c1` 游标 codec，并加入真实版本 2 Payload/Envelope/Event golden。新增 19 项回归后全量为 182 项（捕获内核 167 项、维护与文档脚本 15 项），普通与严格 `ResourceWarning` 模式均通过。顶层公开入口和 `operations.py` 未改，公开读取、append writer、生产配置与生产 Store 均不存在；本批由独立提交 `06cff02` 闭环并已 push 至 `origin/main`，C4B 后续另行获授权。
- **完成 C4B `get_capture`**：公开固定签名的读取入口，按 Event 证明的连续版本链解析 latest/历史版本，在正文输出前验证目标版本全部 Payload、Envelope 与 Event，并经 Store 外、单块不超过 1 MiB 的磁盘 spool 向调用方 sink 交付正文；投影缺失/已知损坏只在内存重建并警告，未知机器 schema/version 失败关闭，唯一无 Event 的 N+1 尾部保持不可见。新增 15 项 GET-01–GET-16 回归后全量为 197 项（捕获内核 182 项、维护与文档脚本 15 项），普通与严格 `ResourceWarning` 模式均通过；本批由独立提交 `666ba18` 闭环并已 push 至 `origin/main`，未创建生产配置或 Store。
- **完成 C4C `list_captures`**：公开固定签名的列表入口，按全 Store 不可变结构验证、内存状态重建、严格筛选、`captured_at DESC, capture_id DESC` 排序和绑定 Store/查询的 `c1` keyset 游标返回页；只对当页当前主正文读取最多 640 byte，精确保留前 160 个 Unicode code point，不全量哈希所有正文或伪称完整 attestation。投影异常与唯一 N+1 尾部产生可归属、稳定排序的 warning，其他不可变矛盾整页失败。新增 15 项 LIST-01–LIST-19 回归后全量为 212 项（捕获内核 197 项、维护与文档脚本 15 项），普通与严格 `ResourceWarning` 模式均通过。本批由独立提交 `231ad09` 闭合并已 push 至 `origin/main`；未实现 append writer，未创建生产配置或 Store，也不自动授权 C4V。
- **完成 C4V 读取阶段验收**：保持生产代码、公共契约与磁盘 schema 不变，新增 2 项公共 API 组合验收，使用运行时生成的真实 4 MiB/64 MiB 正文证明 `capture_text → list_captures → get_capture` 的身份、哈希、字节、稳定幂等回执及有界 I/O 一致；另以公开写入验证静态多页无重复/遗漏，以及页间受控新增只按 keyset 边界可见、从空游标重启获得新鲜视图。GET-01–GET-16、LIST-01–LIST-19、C3V 真实边界与竞态矩阵均重跑通过，全量增至 214 项（捕获内核 199 项、维护与文档脚本 15 项），普通与严格 `ResourceWarning` 模式均通过。本批由独立提交 `1e38f2f` 闭合并已 push 至 `origin/main`；未创建生产配置或 Store。
- **完成 C5-0 追加写入契约收口**：冻结关键字追加请求、独立精确成功结果、`1..999998` expected 上界和必填幂等 key；明确锁内完整性/幂等/目标/CAS 优先级、已提交同 key 命中优先于 CAS、同请求唯一 N+1 尾部窄续封、Event rename 三态现场证据、追加投影时间语义、独立追加 staging 所有权和 APP-01–APP-24。同步 C-035–C-042 与 C5A/C5B/C5V 停点；未修改生产代码、磁盘 schema/golden 或公开 API，当前全量仍为 214 项。本批由独立提交 `ea530ad` 闭合，并于 2026-09-16 push 至 `origin/main`；C5A 尚未授权。
- **建立最小 Windows CI 门禁**：提交 `c4d2c7b` 新增 GitHub Actions `windows-latest` / Python 3.13 验证，在 `main` push、Pull Request 与手动触发时运行普通和严格 `ResourceWarning` 全量测试、`compileall`、`pip check` 与确定性文档检查；actions 使用完整提交 SHA 固定且只授予 `contents: read`。该提交已于 2026-09-16 push，首次远端运行 `35075692046` 的全部步骤成功；这只建立开发验收门禁，不部署项目、不创建生产配置或 Store，也不授权 C5A。
- **完成 C5 追加阶段**：C5A `63a3250` 实现严格追加请求/结果、版本 2 Event/Projection、独立 staging 及提交证据原语；C5B `ab2a613` 公开完整 `append_capture_version`，闭合幂等优先于 CAS、当前 Payload attestation、唯一尾部窄续封、版本/Event 无覆盖提交、最终回读和投影 warning；C5V 以真实双进程同 key/不同 key 竞争及真实 4/64 MiB append → list/get 完成 APP-01–APP-24 验收，当时全量 253 项。
- **完成 C6A 业务事务崩溃恢复**：提交 `84ee1d7` 为每个 capture/append staging 增加 Windows 内核存活租约，只清理可证明归属且已经放弃的固定树；9 个 capture 与 7 个 append `os._exit()` 边界均由新进程恢复，活跃、未知、旧式、额外对象、reparse 与身份变化对象保持不动。当时普通与严格全量均为 258 项。
- **完成 C6B 派生状态重建**：新增与四个日常文本操作分离的 `recovery.rebuild_capture_store_derived_state`。操作在 Store 写锁内先完整验证全部已提交 Item/Version/Event/Envelope、所有 Payload 实际哈希与幂等唯一性，再逐项原子重建缺失、损坏或落后的 `capture.yaml`；只恢复空的幂等/outbox 目录骨架，不发明索引或 job schema，也不修复 staging、未提交尾部或损坏原件。新增 7 项 REC-01–REC-03、写前失败、未知格式保留及真实中断续建回归后全量为 265 项。
- **完成 C6C Store 迁移**：新增与四个日常文本操作分离的 `migration.migrate_capture_store`，要求显式源/目标路径与预期 Store ID；持配置锁和源/目标 Store 写锁，先完整验证源，再以不超过 1 MiB 的块复制稳定树，只接受空目标或逐文件大小/哈希完全匹配的兼容子集，目标字节快照与语义复核均通过后才用同目录临时文件原子替换配置，且永不删除源。写操作取得旧 Store 锁后新增配置绑定复核，阻止切换前排队的请求在切换后回写源。新增 9 项 MIG-01–MIG-05、真实进程复制/切换中断、失败回退、幂等重放与旧写请求竞态回归后全量为 274 项。
- **同步 C5A–C6C 并通过远端门禁**：C5A `63a3250`、C5B `ab2a613`、C5V `a9913e2`、C6A `84ee1d7`、C6B `f686941` 与 C6C `ea8f84e` 已于 2026-09-18 同步至 `origin/main`；Windows CI 运行 `35319645501` 在干净 `windows-latest` / Python 3.13 runner 上首次通过普通与严格 `ResourceWarning` 全量测试、`compileall`、`pip check` 和确定性文档检查。
- **完成方向事实收口并区分批准层级**：确认“不承诺语义零遗漏、不允许静默处理缺口、候选必须绑定证据、RAG/图谱输出不得自动成为可信知识”等治理红线；新增[渐进式知识提炼规范](docs/progressive-knowledge-refinement-spec-渐进式知识提炼规范.md)，将 `full-map`、`hierarchical-map`、`retrieval-first` 的默认路由、Source Ledger 物理契约、检索栈和候选图谱实现明确保留为待实验 Draft。同步 README、需求基线、捕获路由、Capture Envelope、策展悖论、长期规划、提示词说明和设计冲突登记；2026-09-19 两份研究输入已编目为非权威材料。未修改 Capture v1、生产代码、测试契约或生产 Store。
- **完成 R1 产品需求总收口的内容与本地验证**：保留并增强现有需求与治理基线，使其成为唯一 L0 顶层需求入口；补齐目标用户、核心任务、产品/信任分层、稳定 `FR-*`/`NFR-*` 需求 ID、版本范围、成功信号、未决策项与最小追踪矩阵。同步修正 GBrain 首落、Draft Profile、零遗漏审核、生产路径状态和旧实施顺序等漂移，并在捕获路由规范与冲突登记中登记边界；未新增平行 PRD，未修改代码、schema、测试或生产 Store，下一功能门禁仍为需单独授权的 C7。本批由提交 `fa00c7e` 闭合，完成时尚未 push，后已随 `fb61358` 同步至 `origin/main`。
- **完成 2026-09-21 需求分析研究输入登记与本地验证**：将 `0921dsh需求分析.md` 作为 `fa00c7e` 快照后的非权威第三方分析加入研究索引并记录原件 SHA-256；其中关于人工闸门吞吐量、证据载体可校验性和优先级的意见仍需当前权威文档及可复现证据裁决，不构成 R1.1、C7/C8 或其他功能授权。该登记已通过确定性文档护栏和本地测试，由提交 `3967047` 闭合，完成时尚未 push，后已随 `fb61358` 同步至 `origin/main`。
- **完成 D1A/D1B 文档信息架构的内容、本地验证与版本化**：新增 `docs/README.md` 作为唯一编号阅读地图，根 README 路由缩减为文档入口、L0 需求、权威登记、当前编码方案和变更记录；将九份已退出当前权威/执行集的旧方案、愿景、审计清单和 SOP 移入 `archive/2026-design-history/`，补充逐项归档映射、历史状态横幅并修复现行引用。文件名保持稳定，不进行数字前缀批量改名。确定性文档护栏以 31 份现行 Markdown、5 个根路由目标和 57 个结构树文件通过，15 项脚本回归及普通/严格 `ResourceWarning` 两轮 274 项全量测试均通过；由提交 `ba12420` 闭合，完成时尚未 push，后已随 `fb61358` 同步至 `origin/main`。
- **完成 C7-0 受限 CLI 编码前契约收口**：在既有操作契约、实现矩阵、编码方案和冲突登记中冻结 `knowledgeflow-capture` 四个精确命令、请求字段白名单、65,536 byte 严格 JSON 头、正文/EOF 预验证、统一响应头、0/2/70 退出码、stderr/日志脱敏，以及生产 `PathPolicy` 与私有测试能力隔离；登记 C-055–C-058 和 CLI-01–CLI-26，并把实现拆为独立 C7A/C7B/C7V。五个状态锚点及文档护栏中唯一的当前门禁断言同步为 C7A，未增加、删除或弱化测试；未创建 `cli.py`、console entry、生产配置或生产 Store，测试基线仍为 274 项。本批由独立提交 `dbe8329` 封存，完成时尚未 push，后已随 `fb61358` 同步至 `origin/main`。
- **完成 C7A 私有协议能力与安全原语的内容、本地验证与独立版本化**：新增不导出、无 `main()` 的 `src/knowledgeflow_capture/cli.py` 私有 runner，严格处理四操作参数、65,536 byte JSON 头、字段白名单、UTF-8 正文及精确 EOF；写操作先经受信 `PathPolicy` 和既有配置解析器预检上限，再以不超过 1 MiB 的块写入 Store 外独占磁盘 spool。`get_capture` 使用独立输出 spool，规范响应保持核心 `to_dict()` 并固定 0/2/70 与脱敏 stderr。新增 19 项测试覆盖 C7A 可证明的 CLI-01–CLI-13、CLI-17、CLI-19–CLI-24 边界后，本地全量为 293 项（捕获测试 278 项、脚本测试 15 项），普通与严格 `ResourceWarning` 均通过。未修改 `pyproject.toml`、未安装 console entry、未连接真实四操作、未创建生产配置或 Store；本批由 `fb61358` 独立版本化并已同步至 `origin/main`，其下一功能门禁为 C7B。
- **完成 C7B 四操作适配与安装入口的内容、本地验证与独立版本化**：在 `pyproject.toml` 注册固定 `knowledgeflow-capture` console script；生产 `main()` 只从可信包/源码安装上下文构造 `PathPolicy.production`，并把已验证请求一对一分派到既有 `capture_text`、`get_capture`、`list_captures` 与 `append_capture_version`，不复制事务或直接写 Store。测试专用子进程 support 仅从测试代码注入 `PathPolicy.test_owned`，真实安装入口以无写入 smoke test 证明参数、JSON 和环境变量都不能启用测试 policy。新增 7 项集成测试后本地全量为 300 项（捕获测试 285 项、脚本测试 15 项），普通与严格 `ResourceWarning` 均通过；未创建生产配置或 Store，下一功能门禁为需单独授权的 C7V。
- **同步 C7B 并通过远端 Windows 门禁**：C7B 提交 `ea2b80c` 已同步至 `origin/main`；Windows CI 运行 [`35997733639`](https://github.com/bayTong/knowledge-flow/actions/runs/35997733639) 在干净 `windows-latest` / Python 3.13 runner 上完成并成功通过安装、普通与严格 `ResourceWarning` 全量测试、`compileall`、`pip check` 和确定性文档检查。该门禁不部署项目、不创建生产配置或 Store，也不授权 C7V。
- **完成 C7V CLI 阶段验收的内容与本地验证**：新增不进入发布包的并发验收 support 和 5 项 Windows-first 集成验收，闭合真实 4 MiB capture、64 MiB append、两个版本 get、两个真实 CLI 进程同 key 收敛、尾随 byte 核心调用前零提交，以及 stdout 头/正文/flush 失败。临时 venv 中以非 editable 安装验证 console script 可发现且包路径不回指仓库；该检查首次暴露旧 setuptools 对 SPDX 字符串许可证元数据的不兼容，因此仅把等价 MIT 声明改为兼容的 PEP 621 `text` 表形式。普通与严格 `ResourceWarning` 全量均为 305 项（捕获测试 290 项、脚本测试 15 项），`compileall`、`pip check`、文档护栏与生产路径前后快照均通过。未修改 `src/`、公共 API、CLI 协议、Store schema 或错误优先级，未创建生产配置或 Store；内容由独立提交 `0787e60` 版本化并同步至 `origin/main`。
- **完成 R1.3 需求边界澄清的内容修订**：明确只针对已有知识的任务复用既有来源身份，不要求重复创建 Capture；区分最低来源状态、当前任务内检索/回答与持久化语义派生处理的授权；明确 `capture-only` 不触发深度语义处理，并把 `full-map`、`hierarchical-map`、`retrieval-first` 保持为可由实验替换的 Draft 候选方法。本次只修订需求、主题规范和非规范性导读，不改变 Capture v1、C7V 门禁、代码或生产 Store。
- **同步 C7V、修复 CI 可移植性并通过远端门禁**：C7V 内容提交 `0787e60` 的首次 Windows CI 运行 `36526009368` 暴露 CLI-25 离线源码安装对 runner 全局构建后端的隐含依赖；提交 `4999232` 在 CI 安装阶段显式准备与 `pyproject.toml` 一致的 `setuptools==80.9.0`，不放宽禁网或 `--no-build-isolation` 验收。Windows CI 运行 [`36529838017`](https://github.com/bayTong/knowledge-flow/actions/runs/36529838017) 随后在精确提交 `4999232` 上通过安装、305 项普通与严格 `ResourceWarning` 测试、`compileall`、`pip check` 和文档护栏。C7 至此闭合；下一功能门禁为仍需另行授权的 C8，总验收、生产配置、生产 Store 与外部接入均未因此获得授权。
- **完成 C8 本地总验收与说明收口**：以 `896c64c` 为被验收基线，41 项故障/边界/并发/迁移/CLI 定向验收、普通与严格 `ResourceWarning` 两轮各 305 项全量测试、`compileall`、`pip check`、文档护栏、安装入口、仓库卫生和生产路径前后快照均通过；验收前后默认机器配置与生产 Store 均不存在。本机目录元数据 flush 实测为 `unsupported`，所以结论仅支持 `Implemented` 候选，不支持 `Effective` 或抗突然断电声明。双语 README 补充机器协议入口说明，错误/警告表补齐管理操作专用及保留值，文档护栏路由白名单同步纳入 C8 报告且 15 项脚本回归通过；C8 尚待独立提交、精确远端 CI 与用户状态确认，不授权生产初始化或外部接入。
- **闭合 C8 远端门禁并同步限定状态**：C8 证据由独立提交 `63f3a3d` 封存且已推送；[Windows CI 运行 `36544619016`](https://github.com/bayTong/knowledge-flow/actions/runs/36544619016) 在该精确提交上通过安装、普通与严格 `ResourceWarning` 全量测试、编译、依赖和文档检查。用户随后指示同步状态锚点，故新增 `Implemented` 状态并只用于 MVP-0 单机单用户文本捕获内核；整体产品仍非 `Effective`，生产配置/Store 未创建。下一独立门禁为 P0 生产初始化及最小收件箱 dogfood 规划，实施另需明确授权。
- **批准并版本化 P0A/P0A.1 生产 dogfood 方案与限界**：新增一份活动期 P0 实施方案，把最小生产管理、临时 Store 收件箱、精确生产初始化和真实 dogfood 拆为 P0A/P0B/P0C/P0D/P0V 独立门禁；明确迁移/重建不等于备份，P0B 只闭合显式初始化、只读校验、一致性冷备份和新目标恢复，不建设通用备份平台。P0A.1 进一步固定低摩擦文本收件箱这一首要旅程、“待处理”只映射既有未审核状态、首版客户端只保留进程内幂等身份、界面绑定公共四操作而不预定 CLI 传输，并把真实路径、静态保护、无产品级删除和内容敏感度精确授权后置到 P0D。只读预检与提交前复核均确认候选配置/Store 及其父目录不存在；候选 E 盘为固定 NTFS 卷，方案成文时约有 197.26 GiB 可用空间并通过生产路径策略，卷健康仍留作 P0D 时点预检。2026-09-29 综合复核原文已作为非权威研究输入登记。用户批准 P0A.1 顺序与边界；本批仅更新文档入口、护栏白名单和状态断言，下一门禁为需单独授权的 P0B-min，不授权后续编码、生产初始化或真实内容写入。
- **形成 P0B-min 最小生产管理能力的本地候选**：在用户单独授权后新增 `knowledgeflow-capture-admin`，只提供显式 `init/verify/backup/restore`，不扩大日常四操作 CLI。新增严格 `knowledgeflow.capture-backup` v1 Bundle Manifest，固定派生状态/未提交尾部纳入、`.staging` 内容/锁文件排除、Manifest 最后写入、目标叶必须不存在、失败残留保留且不续传、恢复不切配置，以及同盘副本仅为 `operational-copy`。16 项新增测试覆盖规范 Manifest、路径脱敏 CLI、临时非 editable 安装、幂等初始化、非修复校验、冷备份/恢复、四操作组合、零覆盖、篡改、中断、空间不足和文件选择；普通与严格 `ResourceWarning` 全量均为 321/321（捕获 306、脚本/文档 15），文档护栏、编译、依赖和 diff 检查通过。本条不声明已经提交、远端 CI 通过或 P0B `Implemented`，不创建生产配置/Store/备份，也不授权 P0C。
- **本地版本化 P0B-min 并记录远端门禁延期**：上述候选已由本地提交 `aa0a7ea` 独立封存，真实 Git 索引下文档护栏为 0 错误。当前网络问题使 push 与该精确提交 Windows CI 延期，因此仍不把 P0B 标为 `Implemented`，也未使用管理入口创建生产配置、Store 或备份。
- **形成 P0C 最小本地收件箱候选**：在用户明确授权“网络恢复后与 P0B 一起 push”的排程例外下，新增标准库 Tk 桌面入口 `knowledgeflow-inbox` 和只调用四个公共操作的 `InboxSession`。界面支持空列表、稳定分页、新建、完整读取和 CAS 追加完整新版本；“未分配 / 待处理”只映射既有状态，不新增 schema。正文不进入参数、stdout/stderr、日志或磁盘 spool；稳定幂等 key 与正文只在当前进程保留，结果不明时锁定编辑并复用同一请求，崩溃后绝不自动重发。17 项 P0C 测试加入配置缺失零写入、Unicode、真实 4 MiB 边界、真实双会话版本竞争、重试/警告/泄漏边界和安装入口检查；普通全量 338/338（214.768 秒）与最终候选严格 `ResourceWarning` 全量 338/338（164.360 秒，隔离拟提交 Git 索引）通过。该候选在此记录时点尚未复核或提交，不授权 P0D、真实路径或真实内容；后续版本化和远端事实见紧随其后的记录。
- **版本化并同步 P0B/P0C，记录首次合并远端门禁失败**：P0B-min `aa0a7ea` 与 P0C `2a29a1a` 已同步到 `origin/main`。首次 [Windows CI 运行 `36774701119`](https://github.com/bayTong/knowledge-flow/actions/runs/36774701119) 完成安装后，在普通全量中只有安装态 `knowledgeflow-inbox --help` 断言失败：英文 Windows 默认文本编码无法编码中文帮助，入口返回 1。该结果不证明 Store 事务、备份或数据完整性失败，也不允许把 P0B/P0C 标记为 `Implemented`。
- **形成 P0C Windows 控制台 UTF-8 可移植性修复候选**：只在 `knowledgeflow-inbox` 启动时将可重配置的 stdout/stderr 固定为 UTF-8，保留中文帮助和既有退出语义，不修改机器 CLI、四操作、Store 或 schema；既有安装态验收强制 `PYTHONIOENCODING=cp1252:strict` 以复现远端条件。强制复现返回 0，5 项聚焦测试、338/338 普通全量（156.371 秒）与 338/338 严格 `ResourceWarning` 全量（144.776 秒）均通过；测试总数不变。该候选待独立提交、push 和精确远端重跑，不授权 P0D 或生产路径。
- **闭合 P0B/P0C 最终远端门禁并同步限定状态**：UTF-8 可移植性修复由提交 `d149036` 独立封存并同步到 `origin/main`；[Windows CI 运行 `37185470445`](https://github.com/bayTong/knowledge-flow/actions/runs/37185470445) 在该精确提交上通过安装、338 项普通与严格 `ResourceWarning` 全量、编译、依赖和文档一致性检查。P0B-min 与 P0C 因此达到各自已测范围的 `Implemented`；下一门禁为仍需另行精确授权的 P0D。本条不创建生产配置、Store、备份目录或真实 Capture，也不把项目整体标记为 `Effective`。
- **完成 P0D-0 生产初始化操作级规划**：不新增平行方案，在现有 P0 文档内冻结运行环境、候选路径与保护事实、P1–P7 串行检查点、失败关闭条件和必须完整填写的精确授权模板。可移植性按“核心契约—平台 Profile—本机部署绑定—脱敏证据”分层，精确路径只用于本机执行；同盘或物理关系未知可选择 `operational-copy`，只有要求防整盘故障却不能证明独立介质时才阻塞。只读复核确认候选配置/Store 及父目录仍不存在，当前仓库 `.venv` 为 editable 开发安装，卷健康、物理磁盘映射与 BitLocker 状态尚未取得，因此不得推定为安全。本批不安装生产运行环境，不创建目录、配置、Store、备份或真实 Capture；下一步只能先做基于精确候选值的 P0D-P1 只读预检，再请求 P0D-P2 授权。
- **完成 P0D-P1 只读预检与默认布局候选**：P0D-0 已由本地提交 `86f61ff` 封存且尚未 push。只读检查确认运行时代码仍等于远端已验收的 `d149036`，候选路径不存在且通过生产路径策略；当前 `.venv` 是缺少管理/收件箱入口的 editable 安装，本机也没有精确构建后端与 PyYAML wheel 缓存，尚不能离线复现独立非 editable 环境。预检还盘点了旧外置卷候选和不同物理磁盘；默认布局随后改为当前用户 `APP-HOME` 下分设配置、`data\capture-store` 与 `backups`，首份备份只声明同盘 `operational-copy`，其他位置保持可配置。默认祖先未发现宽 ACL，BitLocker 状态因系统拒绝查询而未知，且未发现竞争进程。本轮没有安装、下载或真实数据写入。
- **完成并本地版本化 P0D-P1 最小可行性方向纠偏**：复核确认捕获可靠性设计本身没有错误，但把最小内部 wheel、版本化非 editable 环境、管理员级 BitLocker/ACL 证明和异盘关系都前置，会推迟核心产品价值验证。P0D 因而收缩为低敏感度 pilot：记录精确代码基线后刷新当前仓库 `.venv`，默认使用同一 `APP-HOME` 下的配置、Store 和备份分目录，只接收低敏感度、可替代文本；保护状态允许如实标记为未知。wheel、正式安装包、静态保护强化和异盘灾备保留到分发、私人/高敏内容或更强保护声明前。核心 schema 与操作语义保持平台无关，Windows 专有事实只属于首个 Profile。上述默认布局、测试护栏与方向纠偏由本地提交 `da99650` 独立封存，尚未 push；下一门禁为 P0D-P2 对精确路径、目录创建、`.venv` 刷新和内容限制的单独授权，尚未创建 Pilot Store 或真实 Capture。
- **建立价值优先的唯一执行罗盘候选**：确认项目总体方向仍正确，实际偏差是捕获底座达到当前可靠性目标后仍继续把发布级硬化放在产品价值验证之前。主 PRD 新增稳定优先级原则；权威登记把 P0D/P0V、代表材料协议、Evidence-first 本地检索切片、中小体量轻量策展与大体量检索优先对照、最小工作知识契约、路由/可信晋升和触发式产品化排成唯一顺序，并加入反偏离规则。渐进式提炼规范与双语 README 同步；本批不授权 P0D、语义 schema、RAG、GBrain 或可信写入。
- **完成 P0D-P2/P3 精确授权与 pilot 父目录准备**：用户在看到解析后的本机路径后确认完整低敏感度 pilot 授权，绑定代码基线 `4b21203`，允许刷新当前 `.venv` editable 安装并创建必要父目录。刷新后内部包仍为 `0.1.0.dev0` 且解析到仓库 `src/`，三个 console entry 均存在并以无 Store 写入方式通过 smoke；只创建 `APP-HOME`、数据父目录和备份父目录，配置、Store、备份叶与真实 Capture 仍不存在。继承 ACL 含本机 `CodexSandboxUsers` 读取/执行且静态加密状态未知，因此继续严格限制为低敏感度、可替代文本；下一检查点为 P0D-P4 空 Store 初始化与验证。
- **完成 P0D-P4 空 Pilot Store 初始化与验证**：执行前再次确认授权目标为空、无 reparse 和同名入口进程，11 项管理聚焦测试通过；随后只执行一次固定 4 MiB/64 MiB 阈值的 `init`。路径无关回执、独立 `verify` 和另一个进程的配置重开均成功，Store 身份一致，0 个 Item/Version，备份父目录保持为空。本批未启动收件箱、未写入 Capture、未创建备份叶或执行 restore；下一检查点 P0D-P5 必须由用户本人选择和输入首份低敏感度、可替代文本。
- **完成 P0D-P5 用户首份低敏感度 Capture**：用户本人通过可见 Tk 收件箱选择、输入并保存首份内容，随后确认界面回读正文正确。独立 `list_captures` / `get_capture` 复核确认 Capture 身份、当前版本 1、48 字节正文、Envelope 与正文哈希一致，路由/信任状态保持 `unassigned` / `unreviewed-capture`，且未输出或版本化正文、preview 或幂等键。写入后管理 `verify` 返回 1 个 Item/Version、17 个目录、5 个文件及快照 `sha256:4d785304fc3ef0a038a80802b468be9dad27a0e0bdf66353c6004853ecdf29d3`。
- **完成 P0D-P6/P7 首份操作副本与停点**：用户关闭收件箱并确认全新 `BACKUP-1` 后，只执行一次 `backup`。备份作业 `job_01a10b04-99bb-7c58-960b-9f25f0376a8d` 于 `2026-10-05T07:43:33.313Z` 成功，明确标记为同盘 `operational-copy`；清单与源 Store 的身份、4 MiB/64 MiB 阈值、17 个目录、5 个文件、2917 字节和快照哈希完全一致，清单哈希为 `sha256:ea4c768368b2c5f2b7200aa2a467ea28f03ee55cb72b8a9c39b8c8f1d3062992`。备份后源 Store 独立 `verify` 不变、备份父目录只有该一个叶、无持久 spool 或同名入口进程。未执行 restore、配置切换或 P0V；下一门禁为需另行规划和授权的短周期 P0V。
- **完成 P0V-0 最小执行与验收协议收口**：把宽泛 dogfood 列表收缩为 P0V-1 正常四操作旅程、P0V-2 正常重启/用户控制断网/无破坏错误理解、P0V-3 新同盘操作副本、需单独精确授权的 P0V-R 新目标恢复，以及 P0V-4 脱敏证据停点。真实 Store 禁止强杀写入、写满磁盘、故意损坏或制造锁冲突；成功按操作覆盖、用户理解、完整性和真实恢复证明，不虚构 SLA、Capture 数量或运行天数。本批只修改文档并运行文档护栏，不启动收件箱、不写 Pilot Store、不创建备份/恢复目标、不执行 restore 或配置切换，也不修改产品代码；下一门禁为尚未授权的 P0V-1。
- **完成 P0V-1 正常用户旅程**：用户通过可见收件箱完成既有读取、新建、列表/打开和追加新版本；独立公共回读证明 `v1` 与 `v2` 均完整、旧版本未被覆盖，最终 Store 为 2 个 Item、3 个 Version。用户能够理解保存与版本概念，但界面没有历史版本浏览或“恢复为新版本”入口，形成不阻塞基础存储结论、但阻塞版本管理可用性声明的 `P0V1-UX-01`。
- **完成 P0V-2 重启、离线与安全错误理解**：正常关闭/重开保持事实不变，明确可丢弃的未保存草稿未被提交或伪恢复；真实断网条件下启动、读取和新建成功，空正文以 `invalid_input` 明确未保存。用户主动执行的额外一次新建和一次追加得到归属后，最终 Store 为 4 个 Item、6 个 Version且完整性通过；空正文文案重复提交状态、修正动作不清晰，形成 `P0V2-UX-01`。用户于 2026-10-08 明确同意先纠正当前状态，再按 P0V-3 → P0V-R → P0V-4 串行完成操作副本、全新目标恢复与证据收口；每一步仍受精确目标、零覆盖和失败停点约束。
- **完成 P0V-3 新操作副本**：用户正常关闭收件箱并确认全新 `BACKUP-2` 后，只执行一次 `backup`。作业 `job_01a11aa0-61ef-757e-aad9-d3df62aaee28` 于 `2026-10-08T08:28:00.879Z` 成功并明确标记为同盘 `operational-copy`；公开清单加载器与备份后源 Store `verify` 独立确认同一 Store 身份、4 MiB/64 MiB 阈值、4 个 Item、6 个 Version、36 个目录、23 个文件、15622 字节和快照 `sha256:f8947f4cdaa12591d387c451bea417d6cc1f6e53a82b16040e9ac102d951a095`，清单哈希为 `sha256:eb50656eb87448eefeda4b6953432332b1589a3cb7bf72efaeebec18e117d351`。源 Store 前后不变，目标只含规范清单和 Store，且无持久 spool 或残留入口进程；未执行 restore、配置切换或删除。当前停在 P0V-R 精确全新目标确认前。
- **完成 P0V-R 全新目标恢复演练**：用户在确认精确 `BACKUP-2`、全新 `RESTORE-1`、成功后保留和零覆盖边界后，只执行一次 `restore`。回执明确 `config_switched=false`，同一 Store 的 4 个 Item、6 个 Version、36 个目录、23 个文件、15622 字节和规范快照恢复成功；23 个清单文件随后全部独立重哈希，公共 list/get 又证明活动 Store 与恢复副本的全部历史版本和正文哈希一致，脱敏逻辑证明摘要为 `sha256:82610cb8ed0629ce114fea5c65056474be9e5eefc74120fd126fbdfd126d9c28`。正式配置哈希、指向和源 Store 前后不变，一次性验证配置已移除，恢复副本按授权保留为非活动目标；当前只剩 P0V-4 证据与限定状态收口。
- **完成 P0V-4 证据与限定状态收口**：P0V-1/2/3/R 的真实四操作、正常重启、未保存草稿、离线读写、安全输入失败、第二份同盘操作副本和全新目标恢复证据完整，没有阻塞级数据缺陷；`P0V1-UX-01` 历史版本/恢复入口不可见与 `P0V2-UX-01` 空正文修正提示不清晰作为重要摩擦保留。P0V 只在“本机低敏感度 Pilot Store + 最小收件箱形成初步真实可用性和恢复证据”的范围通过，项目整体仍非 `Effective`。本批仅同步文档和机器门禁，文档检查、8 项脚本测试与差异检查通过；产品代码与测试未变，因此未重跑 338 项产品全量。下一门禁为尚未授权的 D2 文档职责与归档维护批次，之后才分别规划最小历史版本/恢复 UI 修复和 Evidence-first 价值切片。
- **建立唯一项目状态入口**：新增 `docs/project-status-项目状态与当前门禁.md`，唯一维护当前阶段、最近完成点、下一门禁、开放问题和验证入口；主 PRD、设计权威登记、双语 README、稳定契约和已完成实施计划不再复制动态下一步。文档护栏由“五份状态锚点必须同步”改为“整个现行文档集只能有一个锚点”，并保留测试总数相加约束。下一独立批次为 `D2-CONTRACTS` 长期管理与收件箱契约提取；本批不归档文件，不修改产品代码、Pilot 数据或功能优先级。
- **完成 D2-CONTRACTS 稳定契约提取**：新增 Capture Store 管理/备份恢复契约与最小本地收件箱产品规范，分别承接 P0B-min 的 `init/verify/backup/restore`、Backup Bundle v1、零覆盖恢复和 P0C 的四操作薄壳、进程内幂等重试、错误/警告及已知 UX 缺口；把 C7 完整命令、请求/响应帧、退出码和生产/测试隔离从历史实现矩阵迁回四操作契约。主 PRD 只同步追踪关系，P0 方案降为执行证据，未授权历史 UI、删除、归档状态机或新产品功能；下一独立门禁为 `D2-ARCHIVE`。

`pyproject.toml` 中的 `0.1.0.dev0` 是内部捕获包版本，独立于 KnowledgeFlow 文档项目当前的 v2.x 历史版本；正式发布策略待 MVP-0 闭环后再确定。

## v2.2.1 — 2026-08-24

### 脚本与规范对齐（improvement-action-plan P0-1 / P0-2 / P0-3）

- **SOP-003 检查项 6 升级为两档阈值**：>300 行警告（拆分候选）、>500 行错误（必须拆分红线）。原 500 行红线仅存在于脚本实现（`LINE_LIMIT_ERROR`），现写入规范——脚本与规范自创口径的分歧按「对规范是净改进」方向解决
- **SCHEMA 模板第五章注册格式标准化**：注册标签统一以反引号包裹（`` `标签名` ``，不带 `#`），`templates/SCHEMA-template.md` 与 `docs/sop-v2-full.md` SOP-000 内嵌模板同步；`scripts/lint.py` 标签审计改为解析该格式（只认标签体系章内的表格行，向后兼容 `` `#标签` `` 旧格式），并实现「已注册但未使用」提醒——修复原实现对模板格式 SCHEMA 解析恒为空集、标签审计静默失效的缺陷
- **lint.py 补齐 4 项缺失检查**：index 完整性（检查 3）、日志轮转（检查 7，仅报告）、entity 孤立（检查 8，Error 级）、图谱过滤规则（检查 9，仅报告；非 Obsidian 知识库跳过）
- **lint.py 口径对齐**：frontmatter 检查从 3 字段扩展至 7 字段 + type 合法性 + title 格式匹配（检查 4）；孤立页面从 Notice 升为 Error（检查 2，与 SOP-003 输出级别一致）；新增行内代码 wikilink 排除（检查 1，SOP-003 实现说明要求）；所有消息加 `[检查N]` 前缀，与 SOP-003 检查项编号一一对应
- **脚本 Windows 健壮性**：三个脚本 stdout/stderr 重配置为 UTF-8（修复 GBK 控制台 `UnicodeEncodeError` 崩溃）、文件读取改为 `utf-8-sig`（修复带 BOM 文件 frontmatter 误判缺失）
- **index-generator.py 对齐 SCHEMA 规范**：slug 改为纯文件名（不含路径与扩展名，SCHEMA 第六章）；条目尾注从「type — tags」改为机械式一句话摘要（正文首段截断，frontmatter 缺失时降级为文件名，注明建议人工润色）；分组对齐第七章（concept/comparison 按模块、entity 归「实体」段、query 归「问答」段）；头部统计行对齐 SOP-000 步骤 4 模板；`--write` 显式 LF 写入，预览输出与写入内容字节级一致；文档字符串补免责说明（全量重生成会覆盖手工摘要，建议配合 git 审阅）

---

## v2.2 — 2026-07-13

### 自适应提取分层 + 独立覆盖审计

核心变更：从一刀切多轮次改为自适应模式——默认单次提取 + 独立覆盖审计，长文自动升级。

**新增文件**：
- `prompts/sop-001-modeA.md` — Mode A 提取模板（第 1-9 节，默认推荐）
- `prompts/sop-001-modeA-fast.md` — Mode A-fast 快速路径（含自检覆盖报告）
- `prompts/sop-001-modeA-auditor.md` — Mode A 独立覆盖审计员（第 10 节）
- `prompts/sop-001-modeB-pass1-entities-claims.md` — Mode B Pass 1（实体+论点合并）

**改名**：统一 `modeA/modeB/modeBC/modeC` 命名规则
- `sop-001-rough-reader.md` → `sop-001-modeBC-assembler.md`
- `sop-001-pass1-entities.md` → `sop-001-modeC-pass1-entities.md`
- `sop-001-pass2-relationships.md` → `sop-001-modeBC-pass2-relationships.md`
- `sop-001-pass3-claims.md` → `sop-001-modeC-pass3-claims.md`

**策展地图新第 10 节「覆盖报告」**（不新增 LLM 调用）：
- Mode A 默认：独立审计（auditor 对照源文）
- Mode A-fast 可选：自检覆盖
- Mode B/C：交叉校验（assembler 对照独立 Pass 产出）

**四种提取模式**：
- Mode A（默认）：提取 + 独立审计 + 策展 = 3 次 LLM
- Mode A-fast：提取含自检 + 策展 = 2 次 LLM（< 3000 字可选）
- Mode B：2 Pass + 轻量组装 + 策展 = 4 次 LLM（> 10000 字自动触发）
- Mode C：3 Pass + 完整组装 + 策展 = 5 次 LLM（人审触发）

**文档更新**：
- `extraction-interface.md` 新增顶层第七节，用于定义策展地图第 10 节覆盖报告格式
- `prompts/README.md` 重写（四种模式选择指南 + 人审流程）
- `docs/sop-v2-full.md` 策展地图 9→10 节，并列记录源文规模、读取方式与模式选择等不同阈值用途
- `docs/build-plan.md` 阶段 1 更新
- `docs/adaptive-extraction-plan.md` — 新增修改方案文档

## v2.1 — 2026-07-11

### 项目工程化补全——prompts/ 目录 + 术语统一 + 文档合并

v2.0 完成了方法论核心（SOP-000~006），但缺少让用户「拿起来就能用」的桥接层。v2.1 将其补齐。

#### 新增：`prompts/` 目录（8 个文件）

项目核心交付物的缺失部分——LLM-agnostic 提示词模板，使用 `{{PLACEHOLDER}}` 占位符，不绑定任何特定 LLM 工具。

| 文件 | 用途 |
|------|------|
| `prompts/README.md` | 模板使用说明（格式、占位符、接入不同 LLM 工具的方式） |
| `prompts/sop-001-rough-reader.md` | SOP-001 组装模板（将三份 Pass 输出组装为完整策展地图） |
| `prompts/sop-001-pass1-entities.md` | Pass 1：全景概括 + 提取层次 + 实体清单 |
| `prompts/sop-001-pass2-relationships.md` | Pass 2：关系提取 |
| `prompts/sop-001-pass3-claims.md` | Pass 3：论点与主张提取 |
| `prompts/sop-002-curator.md` | SOP-002 策展入库（基于审核过的策展地图） |
| `prompts/sop-003-lint.md` | SOP-003 知识库健康扫描 |
| `prompts/extraction-interface.md` | 提取接口技术规范（所有 prompt 的格式权威参考） |

所有模板使用 `.md` 扩展名——在 GitHub 上自动渲染标题/表格/代码块，复制进 LLM 时 markdown 标记本身是结构信号。

#### 术语统一：「阅读地图」→「策展地图」

> （本节为历史边界标注；v2.0 条目中的术语已随 v2.1 同步更新为「策展地图」。v2.0 原始文档使用的是「阅读地图」。）

全局改名原因：「策展地图（Curation Map）」更精确地描述了该产物的角色——它是穷举提取的结构化产物，是人审和策展决策的核心参考面。「阅读」暗示被动消费，与 SOP-002「策展入库」术语不一致。

影响范围（6 个文件）：`docs/sop-v2-full.md`、`README.md`、`README-zh.md`、`CHANGELOG.md`、`templates/SCHEMA-template.md`、`examples/curation-map-example.md`（文件重命名）。`archive/v1.0/` 保留历史术语不变。

#### 文档合并

- `docs/second-brain-roadmap.md` → 精简为 `docs/second-brain-vision.md`（战略愿景，1 页）。原详细执行计划保留在 `docs/build-plan.md` 中。
- `docs/project-gap-analysis.md` → **删除**。一次性快照，状态已失准，内容已被 build-plan 覆盖。
- `docs/build-plan.md` 定为外置第二大脑项目的**唯一权威路线图**。

#### 其他

- `.gitignore`：补齐 Python 缓存规则（`__pycache__/`, `*.py[cod]`, `*.pyo`）
- README ×2：更新项目结构图（反映 `prompts/` 目录和 `docs/` 下的实际文件）；加入 `prompts/` 使用说明

---

## v2.0 — 2026-07-06

### 架构重构：两阶段管线（粗读器 → 策展入库）

v1.0 的核心矛盾：提取和策展合并在同一 SOP 中，Agent 必须在穷举提取概念的同时暗中做重要性判断——这两个认知任务是冲突的。Agent 提取出的东西已经是它「认为值得入库」的子集，用户无法验证 Agent 漏掉了什么。

v2.0 的解决方案：将原 SOP-001 拆分为两个独立的 SOP。

#### 新增 SOP-001：粗读器（策展地图）

- **穷举提取，不做筛选**（C5 硬约束）——Agent 从原料中提取所有概念、实体、关系、事实主张，不判断重要性
- **7 字段提取接口**——每条提取必须包含：标识符、名称、所属层次、一句话描述、原文引用、置信度、不确定原因
- **5 种不确定原因分类**——来源不可靠 / Agent 理解局限 / 原文模糊 / 信息不完整 / 总结压缩损失
- **全景概括**——先逐段覆盖缩写，再拼接整合为连贯全景叙述，确保 Agent 在提取前真正理解了原料
- **缺口分析**——基于用户目标（先问用户「你想从中获得什么」）列出原料应涵盖但未涵盖的内容
- **SCHEMA 建议**——冷启动时推导完整 SCHEMA，已有 SCHEMA 时做差异分析
- **Agent 建议严格隔离**——独立子标题 + 允许/禁止清单，防止建议污染事实层
- **7 条硬约束**（C1–C7）——其中 5 条为禁止项（☒），2 条为强制义务（☑）
- **规模分级**——四级原料规模（<500 / 500-5000 / 5000-20000 / >20000 字），各有不同策略
- **覆盖盲区声明**（C6）——超长原料必须列出未细读的章节
- **轻量领域门禁**——从「确定属于」降级为「不显然不属于」，粗读前快速筛而非阻止
- ☒ 不创建任何 wiki 页面——只产策展地图，等人审核

#### 新增 SOP-002：策展入库

吸收原 SOP-001 的步骤 2（定向）、2.5（领域门禁）、4（决策树）、5（写入+4 套模板+8 条通用约束）、5.0→4（SCHEMA 同步检查）、6（导航更新）、7（自检 8 项）、8（报告）。

关键变更：

- **操作对象从「Agent 自己的提取结果」改为「策展地图中用户确认入库的条目」**——Agent 只处理人类已审核的内容
- **新增步骤 1（验证前置）**——验证 raw 原料 SHA256 + 策展地图审核状态 + 提取确认条目 + 确认 SCHEMA 版本
- **全文搜索不可跳过**——步骤 2.3 从建议升级为硬性要求，且给出了跳过它会导致的退化模式（两份页面讲同一件事）
- **标签注册死锁问题解决**——v1.0 中标签需先在 SCHEMA 注册才能使用，但标签定义又来自对原料的理解。v2.0 的粗读器只提取不注册，策展时才在步骤 4 统一注册，顺序天然合理

#### 其他 SOP 变更

| SOP | 变更 |
|-----|------|
| SOP-000 | **6 处微调**：步骤 2 新增 `raw/_curation-maps/` 目录；步骤 6 拆为 6a（粗读）→ 6b（人审）→ 6c（策展）；步骤 7 检查项 ⑤ 增补策展地图要求、检查项 ⑥ 保证来源改为 SOP-002；步骤 9 报告增加「用户暂停审核」中间态 |
| SOP-003 | 原 SOP-002，编号后移。**新增检查项 9：图谱过滤规则**——检测 Obsidian 关闭时自动覆写 `graph.json` 导致 SCHEMA 文件污染图谱的已知陷阱。轻量版仍为 3 项；完整版从 8 项增至 9 项。交叉引用已同步更新 |
| SOP-004 | 原 SOP-003，编号后移。交叉引用已同步更新 |
| SOP-005 | 原 SOP-004，编号后移。交叉引用已同步更新 |
| SOP-006 | 原 SOP-005，编号后移。**出口修改**：用户选「入库」后不再走原 SOP-001，改为：导出对话 + 计算 SHA256 + 生成简化策展地图 → 调用 SOP-002（策展入库）。跳过完整粗读器的理由：用户刚刚参与了对话，已经实时审核了内容——不需要再粗读一遍 |

#### 编号对照

```
旧 → 新
SOP-000 → SOP-000（6 处微调）
SOP-001 → 删除（拆分为新 SOP-001 + SOP-002）
SOP-002 → SOP-003
SOP-003 → SOP-004
SOP-004 → SOP-005
SOP-005 → SOP-006
```

---

## v1.0 — 初版

### 首次完整 SOP 体系

- **6 个 SOP**：SOP-000（初始化）至 SOP-005（话题切换提炼提案）
- **单阶段摄入**：原 SOP-001 同时完成提取、决策、写入——一步从原料到 wiki 页面
- **三层防御体系**：SOP-001 自检（增量）→ SOP-002 全量 Lint（累积）→ SOP-003 SCHEMA 一致性（连锁）
- **领域门禁**三级出口：☑ 继续 / ⚠ 部分提取 / ☒ 人工介入
- **4 套页面模板**：concept / comparison / entity / query
- **8 条写入通用约束**
- **批量摄入模式**：多原料时合并执行查重
- **人类审查面缺失**——这是 v1.0 最根本的架构局限，也是驱动 v2.0 重构的核心动力

### 归档位置

v1.0 原始文档已归档至 [`archive/v1.0/`](archive/v1.0/)：
- [`sop-v1-original.md`](archive/v1.0/sop-v1-original.md) — v1.0 完整 SOP 规范原文
- [`README.md`](archive/v1.0/README.md) — v1.0 局限性说明
