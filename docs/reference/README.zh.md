# 概览

<!-- Compatibility anchors for existing incoming links. -->
<a id="专题笔记"></a>
<a id="设计文档归档"></a>


在这里查阅 Python API、CLI 命令和配置。按任务操作时阅读产品指南，需要当前参数和设置明细时阅读生成参考页。

## Python API

- [API 总览](API.zh.md)：核心组件和导入方式。
- [函数](api/agent.zh.md)：装饰器参数、元数据和执行行为。
- [运行时](api/runtime.zh.md)：模型请求与运行时约定。
- [模型服务](api/providers.zh.md)：运行时创建和模型服务接口。

## CLI 与配置

| 使用指南 | 生成明细 |
|---|---|
| [CLI 用法](cli.zh.md) | [全局参数](cli/README.zh.md)及侧栏中的各命令参考页。 |
| [配置](config.zh.md) | [配置键](config-keys.zh.md)、默认值和生效时机。 |
| [模型服务设置](../models/providers.zh.md) | [模型服务清单](provider-registry.zh.md)、协议和环境变量名。 |

生成参考页提供完整中英文说明。命令名、参数、配置键和协议值在两种语言中保留源代码写法。条目清单来自代码，并随站点重新生成。

## 诊断

[诊断包](diagnostics.zh.md)说明支持 ZIP 包含的内容和敏感字段的脱敏方式。

## 工程设计

[设计栏目](design/README.zh.md)按子系统组织当前设计。每个主题维护一份文档，设计修改直接更新正文，历史由 Git 保留。计划中的行为在实现状态部分注明。这些工程说明与产品指南互相补充。
