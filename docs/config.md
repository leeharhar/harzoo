## **配置说明**

Harzoo 是一个**AI框架**，其大脑、行为与专业能力完全由配置文件夹中的文件决定，你可以通过通过自定义这些文件来构建你自己的AI。配置文件夹的目录结构如下：

```text
~/.harzoo/
└── config/            
    ├── config.json              # 默认启动 profile 配置
    ├── profiles/                # 存放 profile 文件（*.md）
    ├── tools/                   # 存放工具文件（*.py）
    └── skills/                  # 存放技能文件（*.md）
```
> 补充：首次启动 Harzoo 时，会在本机自动创建上述文件夹及`config.json` 文件。

## **配置步骤**

> 为了帮助用户快速构建专属智能体，官方提供了 [智能体构建师] ，可根据用户构建智能体的需求自动生成配置文件。[智能体构建师] 包含：1 个profile文件：`harzoo_builder.md` 和 8 个tool文件：`shell.py`、`read.py`、`write.py`、`edit.py`、`grep.py`、`glob.py`、`webfetch.py`、`compact_context.py`

以配置官方的 ** [智能体构建师] ** 为例，步骤如下：

1. 下载 `harzoo_builder.md`，将其中的 `api_key`、`base_url`、`model_name` 替换为你自己的大模型 API 的值，保存后放入 `~/.harzoo/config/profiles/`；
2. 在 `~/.harzoo/config/config.json` 将`xxxx.md`修改成`harzoo_builder.md`；
3. 下载上述的 8 个工具文件，直接将其放入 `~/.harzoo/config/tools/`；
4. 重启 Harzoo 生效，即可与 [智能体构建师] 进行交流。

> 📍 文件夹位置说明 📍

> - macOS：右击 `访达` -> 点击 `前往文件夹` -> 输入 `~/.harzoo/config`
> - Windows：打开 `文件资源管理器` -> `地址栏` 输入 `%USERPROFILE%\.harzoo\config` 后回车
> - Linux：打开 `文件管理器` -> `地址栏` 输入 `~/.harzoo/config` 后回车

<br>
!!! warning "安全风险说明（请阅读）"
    Harzoo 的安全风险取决于 profile 中 `tool_names` 所启用的工具能力（例如 `Read` 可读文件、`Shell` 可执行命令操作电脑、`WebFetch` 可访问网络）。工具可能会读取 profile 中的`api_key`或电脑上其他私人数据进行外传。**因此，来自外部的、非官方的 tool、skill 和 profile 文件 可能存在恶意行为，请一定警惕！！！不要轻易相信来源不明的配置文件**。

## **官方配置文件下载**

> 以下文件也为开源项目 Harzoo 的一部分，适用 [MIT License](https://github.com/leeharhar/harzoo/blob/main/LICENSE)。

**profile 文件**


| 中文简称   | agent_name       | 版本         | 能力说明                                                                                 | 下载                                                                    |
| ------ | ---------------- | ---------- | ---------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| 智能体构建师 | `harzoo_builder` | 2026-05-27 | 设计智能体方案并生成对应的配置文件 | [harzoo_builder.md](/downloads/assets/config/profiles/harzoo_builder.md) |

> 当前的 [智能体构建师] 仅支持操作配置文件，操作Harzoo内核或者外接UI等先进功能会持续更新.

**tool 文件**


| 类别     | tool_name          | 版本         | 能力说明                                      | 下载                                                                    |
| ------ | ------------------ | ---------- | --------------------------------------- | --------------------------------------------------------------------- |
| 智能体控制  | `LoadSkill`        | 2026-05-24 | 按需加载 skill 正文（须 profile 声明 skill_names） | [load_skill.py](/downloads/assets/config/tools/load_skill.py)        |
| 智能体控制  | `CompactContext`   | 2026-05-22 | 压缩上下文：摘要较早消息并保留最近若干条                    | [compact_context.py](/downloads/assets/config/tools/compact_context.py)   |
| 智能体控制  | `SwitchProfile`    | 2026-05-22 | 切换主智能体 profile（模型、提示词、工具集）              | [switch_profile.py](/downloads/assets/config/tools/switch_profile.py)    |
| 智能体控制  | `SubtaskAgent`     | 2026-05-22 | 以子 profile 同步运行委派子任务                    | [subagent.py](/downloads/assets/config/tools/subagent.py)          |
| 文件与终端  | `Shell`            | 2026-05-30 | 执行 Shell 命令（Windows 固定 PowerShell，Unix 固定 Bash） | [shell.py](/downloads/assets/config/tools/shell.py)            |
| 文件与终端  | `Read`             | 2026-05-22 | 读取文件内容                                  | [read.py](/downloads/assets/config/tools/read.py)              |
| 文件与终端  | `Write`            | 2026-05-22 | 写入文件（自动创建父目录）                           | [write.py](/downloads/assets/config/tools/write.py)             |
| 文件与终端  | `Edit`             | 2026-05-22 | 按精确匹配替换文件中的文本                           | [edit.py](/downloads/assets/config/tools/edit.py)              |
| 文件与终端  | `Grep`             | 2026-05-22 | 在文件中按正则搜索                               | [grep.py](/downloads/assets/config/tools/grep.py)              |
| 文件与终端  | `Glob`             | 2026-05-22 | 按 glob 模式查找文件                           | [glob.py](/downloads/assets/config/tools/glob.py)              |
| 网络与浏览器 | `WebFetch`         | 2026-05-22 | 抓取 URL 并提取网页正文                          | [webfetch.py](/downloads/assets/config/tools/webfetch.py)          |
| 网络与浏览器 | `Browser`          | 2026-05-22 | Playwright 浏览器自动化（快照 / ref 操作）          | [browser.py](/downloads/assets/config/tools/browser.py)           |
| 文档处理   | `DocumentRead`     | 2026-05-22 | 读取 pdf、docx、xlsx 等常见文档                  | [document_read.py](/downloads/assets/config/tools/document_read.py)     |
| 文档处理   | `DocumentEdit`     | 2026-05-22 | 编辑结构化文档（常见格式）                           | [document_edit.py](/downloads/assets/config/tools/document_edit.py)     |
| 文档处理   | `DocumentGenerate` | 2026-05-22 | 按结构化载荷生成文档                              | [document_generate.py](/downloads/assets/config/tools/document_generate.py) |
| 桌面 GUI | `GuiScreenshot`    | 2026-05-22 | 截取桌面截图供 GUI 规划使用                        | [gui_screenshot.py](/downloads/assets/config/tools/gui_screenshot.py)    |
| 桌面 GUI | `GuiActuator`      | 2026-05-22 | 执行桌面鼠标与键盘操作                             | [gui_actuator.py](/downloads/assets/config/tools/gui_actuator.py)      |


