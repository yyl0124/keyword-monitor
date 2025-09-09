"""
关键词监听订阅插件

监听指定聊天频道的消息，当检测到配置的关键词时，
自动向订阅频道发送通知消息，实现消息订阅和关键词提醒功能。

## 主要功能

- **多频道监听**: 支持同时监听多个私聊或群聊频道
- **关键词匹配**: 支持为每个监听频道配置独立的关键词列表
- **灵活订阅**: 每个监听频道可以配置不同的通知目标频道
- **消息模板**: 支持自定义通知消息格式
- **多种匹配模式**: 支持模糊匹配、精确匹配和正则表达式匹配
- **通知控制**: 可配置通知间隔，避免频繁通知

## 配置说明

### 监听配置格式
每个监听项格式：`监听频道|关键词1,关键词2|通知频道`
- 监听频道：要监听的聊天频道标识
- 关键词列表：用逗号分隔的关键词
- 通知频道：触发关键词时发送通知的目标频道

### 频道标识格式
- 私聊：`onebot_v11-private_QQ号`
- 群聊：`onebot_v11-group_群号`

### 正则表达式支持
当匹配模式设置为"正则表达式"时，关键词将被视为正则表达式模式：
- `\b错误\d+\b` - 匹配"错误123"、"错误456"等
- `(紧急|urgent)` - 匹配"紧急"或"urgent"
- `@\w+` - 匹配@用户名格式
- `订单.*完成` - 匹配"订单XXX完成"

## 常见使用示例

### 普通关键词监听：
```
onebot_v11-group_123456|重要,紧急,@管理员|onebot_v11-private_789012
onebot_v11-private_111222|订单,发货|onebot_v11-group_333444
```

### 正则表达式监听：
```
onebot_v11-group_技术群|\b错误\d+\b,异常.*数据库|onebot_v11-private_运维
onebot_v11-group_客服群|投诉.*产品,退款.*申请|onebot_v11-group_管理群
```


## 正则表达式语法参考

### 基础符号
- `\b` - 单词边界，精确匹配完整单词
- `\w` - 匹配字母、数字、下划线
- `\d` - 匹配数字
- `.` - 匹配任意字符
- `*` - 前面字符可重复0次或多次
- `+` - 前面字符必须出现1次或多次
- `?` - 前面字符可选（0次或1次）

### 分组和选择
- `()` - 分组
- `|` - 或运算符（在括号内）
- `[]` - 字符集合

### 常用示例

#### 精确匹配
```
\b重要\b          # 只匹配"重要"，不匹配"不重要"
```

#### 多选一
```
(紧急|urgent)     # 匹配"紧急"或"urgent"
```

#### 数字匹配
```
\d+              # 匹配任意数字
错误\d+          # 匹配"错误123"、"错误456"
```

#### @用户匹配
```
@\w+             # 匹配"@张三"、"@admin"
@管理员           # 匹配"@管理员"
```

#### 状态匹配
```
订单.*完成        # 匹配"订单ABC完成"
```

### 配置示例转换

原始配置：
```
onebot_v11-group_123456|重要,紧急,@管理员|onebot_v11-private_789012
```

正则版本：
```
onebot_v11-group_123456|\b重要\b,\b紧急\b,@管理员|onebot_v11-private_789012
```

进阶版本：
```
onebot_v11-group_123456|(重要|紧急|urgent),@\w*管理员,错误\d+|onebot_v11-private_789012
```
"""

from typing import List, Optional
import time
import json
import re
from datetime import datetime

from nekro_agent.api import core
from nekro_agent.api.message import ChatMessage, send_text
from nekro_agent.api.schemas import AgentCtx
from nekro_agent.api.signal import MsgSignal
from nekro_agent.api.plugin import NekroPlugin, ConfigBase, ExtraField, SandboxMethodType
from pydantic import Field

# 创建插件实例
plugin = NekroPlugin(
    name="关键词监听订阅",
    module_name="keyword_monitor",
    description="监听指定聊天的关键词，支持正则表达式，触发时向订阅频道发送通知消息。",
    version="2.0.1",
    author="xiaoyu",
    url="https://github.com/yyl0124/keyword-monitor",
)


# 插件配置
@plugin.mount_config()
class KeywordMonitorConfig(ConfigBase):
    """关键词监听订阅配置"""

    MONITOR_RULES: List[str] = Field(
        default=[],
        title="监听规则列表",
        description="格式：监听频道|关键词1,关键词2|通知频道。频道格式示例：onebot_v11-group_123456 或 onebot_v11-private_789012",
        json_schema_extra=ExtraField(
            is_textarea=True,
            placeholder="onebot_v11-group_123456|重要,紧急|onebot_v11-private_789012"
        ).model_dump()
    )
    
    MATCH_MODE: int = Field(
        default=0,
        title="匹配模式",
        description="0=模糊匹配（包含关键词即触发），1=精确匹配（完全匹配关键词），2=正则表达式匹配",
    )
    
    NOTIFY_TEMPLATE: str = Field(
        default="🔔 关键词提醒\n频道：{channel_name}\n关键词：{keyword}\n内容：{content}\n时间：{time}",
        title="通知消息模板",
        description="支持变量：{channel_name} {channel_id} {keyword} {content} {time}",
        json_schema_extra=ExtraField(
            is_textarea=True
        ).model_dump()
    )
    
    NOTIFY_INTERVAL: int = Field(
        default=60,
        title="通知间隔（秒）",
        description="同一监听规则的最小通知间隔，避免频繁通知",
    )
    
    REGEX_TIMEOUT: float = Field(
        default=1.0,
        title="正则表达式超时时间（秒）",
        description="防止复杂正则表达式导致性能问题",
    )
    
    ENABLE_DEBUG: bool = Field(
        default=False,
        title="调试模式",
        description="启用后会在日志中输出详细的匹配过程",
    )


# 初始化插件
@plugin.mount_init_method()
async def initialize_plugin():
    """插件初始化"""
    core.logger.info(f"插件 '{plugin.name}' 正在初始化...")
    
    config = plugin.get_config(KeywordMonitorConfig)
    rules_count = len(config.MONITOR_RULES)
    
    if rules_count > 0:
        core.logger.info(f"已加载 {rules_count} 条监听规则")
        
        # 验证正则表达式
        if config.MATCH_MODE == 2:
            core.logger.info("正则表达式模式已启用，正在验证规则...")
            for idx, rule_str in enumerate(config.MONITOR_RULES, 1):
                parsed = parse_rule(rule_str)
                if parsed:
                    _, keywords, _ = parsed
                    for keyword in keywords:
                        if not validate_regex(keyword):
                            core.logger.warning(f"规则{idx}中的正则表达式无效: {keyword}")
        
        for idx, rule_str in enumerate(config.MONITOR_RULES, 1):
            parts = rule_str.split('|')
            if len(parts) == 3:
                mode_desc = ["模糊", "精确", "正则"][config.MATCH_MODE]
                core.logger.info(f"规则{idx}: 监听 {parts[0]}, 关键词 [{parts[1]}] ({mode_desc}模式), 通知到 {parts[2]}")
    else:
        core.logger.warning("未配置任何监听规则")
    
    core.logger.success(f"插件 '{plugin.name}' 初始化完成")


def parse_rule(rule_str: str) -> Optional[tuple]:
    """解析单条监听规则
    
    Returns:
        (monitor_channel, keywords_list, notify_channel) 或 None
    """
    parts = rule_str.strip().split('|')
    if len(parts) != 3:
        return None
    
    monitor_channel = parts[0].strip()
    keywords_str = parts[1].strip()
    notify_channel = parts[2].strip()
    
    if not all([monitor_channel, keywords_str, notify_channel]):
        return None
    
    keywords = [kw.strip() for kw in keywords_str.split(',') if kw.strip()]
    if not keywords:
        return None
    
    return (monitor_channel, keywords, notify_channel)


def validate_regex(pattern: str) -> bool:
    """验证正则表达式是否有效
    
    Args:
        pattern: 正则表达式模式
        
    Returns:
        是否有效
    """
    try:
        re.compile(pattern)
        return True
    except re.error:
        return False


def check_keywords(text: str, keywords: List[str], mode: int, timeout: float = 1.0) -> Optional[str]:
    """检查文本是否包含关键词
    
    Args:
        text: 要检查的文本
        keywords: 关键词列表
        mode: 匹配模式 (0=模糊, 1=精确, 2=正则)
        timeout: 正则表达式超时时间
    
    Returns:
        匹配到的关键词，或 None
    """
    for keyword in keywords:
        try:
            if mode == 0:  # 模糊匹配
                if keyword in text:
                    return keyword
            elif mode == 1:  # 精确匹配
                words = text.split()
                if keyword in words:
                    return keyword
            elif mode == 2:  # 正则表达式匹配
                # 验证正则表达式
                if not validate_regex(keyword):
                    core.logger.warning(f"无效的正则表达式，跳过: {keyword}")
                    continue
                
                # 编译正则表达式
                pattern = re.compile(keyword)
                
                # 执行匹配（带超时保护）
                import signal
                
                def timeout_handler(signum, frame):
                    raise TimeoutError("正则表达式匹配超时")
                
                # 设置超时
                old_handler = signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(int(timeout))
                
                try:
                    match = pattern.search(text)
                    if match:
                        return keyword
                finally:
                    # 清除超时
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old_handler)
                    
        except TimeoutError:
            core.logger.warning(f"正则表达式匹配超时，跳过: {keyword}")
            continue
        except Exception as e:
            core.logger.error(f"关键词匹配时出错: {keyword}, 错误: {e}")
            continue
    
    return None


async def get_last_notify_time(rule_key: str) -> float:
    """获取某规则的最后通知时间"""
    time_str = await plugin.store.get(store_key=f"notify_time_{rule_key}")
    return float(time_str) if time_str else 0


async def set_last_notify_time(rule_key: str, timestamp: float):
    """设置某规则的最后通知时间"""
    await plugin.store.set(store_key=f"notify_time_{rule_key}", value=str(timestamp))


# 用户消息回调
@plugin.mount_on_user_message()
async def handle_user_message(_ctx: AgentCtx, message: ChatMessage) -> MsgSignal | None:
    """处理用户消息，检查是否触发关键词"""
    
    try:
        config = plugin.get_config(KeywordMonitorConfig)
        
        # 获取当前频道
        current_channel = _ctx.chat_key
        if not current_channel:
            return None
        
        if config.ENABLE_DEBUG:
            core.logger.debug(f"[监听] 收到消息，频道: {current_channel}")
        
        # 检查所有监听规则
        for rule_str in config.MONITOR_RULES:
            parsed = parse_rule(rule_str)
            if not parsed:
                continue
            
            monitor_channel, keywords, notify_channel = parsed
            
            # 检查是否是要监听的频道
            if monitor_channel != current_channel:
                continue
            
            if config.ENABLE_DEBUG:
                mode_desc = ["模糊", "精确", "正则"][config.MATCH_MODE]
                core.logger.debug(f"[监听] 匹配到监听频道，检查关键词: {keywords} ({mode_desc}模式)")
            
            # 检查关键词
            matched_keyword = check_keywords(
                message.content_text,
                keywords,
                config.MATCH_MODE,
                config.REGEX_TIMEOUT
            )
            
            if not matched_keyword:
                continue
            
            core.logger.info(f"[监听] 触发关键词 '{matched_keyword}'")
            
            # 检查通知间隔
            rule_key = f"{monitor_channel}_{notify_channel}"
            last_time = await get_last_notify_time(rule_key)
            current_time = time.time()
            
            if current_time - last_time < config.NOTIFY_INTERVAL:
                if config.ENABLE_DEBUG:
                    core.logger.debug(f"[监听] 通知间隔未满，跳过")
                continue
            
            # 构建通知消息
            notify_text = config.NOTIFY_TEMPLATE.format(
                channel_name=_ctx.channel_name or "未知频道",
                channel_id=_ctx.channel_id or "未知",
                keyword=matched_keyword,
                content=message.content_text[:200],
                time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
            
            # 发送通知
            try:
                await send_text(
                    chat_key=notify_channel,
                    message=notify_text,
                    ctx=_ctx
                )
                
                # 更新最后通知时间
                await set_last_notify_time(rule_key, current_time)
                
                core.logger.info(f"[监听] 已发送通知到 {notify_channel}")
                
            except Exception as e:
                core.logger.error(f"[监听] 发送通知失败: {e}")
    
    except Exception as e:
        core.logger.error(f"[监听] 处理消息时出错: {e}")
    
    # 不阻止消息的正常处理
    return None


# 沙盒方法：查看监听规则
@plugin.mount_sandbox_method(
    method_type=SandboxMethodType.TOOL,
    name="list_monitor_rules",
    description="列出所有关键词监听规则"
)
async def list_monitor_rules(_ctx: AgentCtx) -> str:
    """列出当前配置的所有监听规则
    
    Returns:
        格式化的规则列表
    """
    config = plugin.get_config(KeywordMonitorConfig)
    
    if not config.MONITOR_RULES:
        return "当前没有配置任何监听规则"
    
    mode_names = ["模糊匹配", "精确匹配", "正则表达式"]
    current_mode = mode_names[config.MATCH_MODE] if config.MATCH_MODE < len(mode_names) else "未知模式"
    
    result = f"📋 当前监听规则 ({current_mode})：\n"
    result += "=" * 40 + "\n"
    
    for idx, rule_str in enumerate(config.MONITOR_RULES, 1):
        parsed = parse_rule(rule_str)
        if parsed:
            monitor, keywords, notify = parsed
            result += f"\n规则 {idx}:\n"
            result += f"  监听: {monitor}\n"
            result += f"  关键词: {', '.join(keywords)}\n"
            result += f"  通知到: {notify}\n"
            
            # 正则表达式模式下验证规则
            if config.MATCH_MODE == 2:
                invalid_patterns = [kw for kw in keywords if not validate_regex(kw)]
                if invalid_patterns:
                    result += f"  ⚠️ 无效正则: {', '.join(invalid_patterns)}\n"
            
            # 显示最后通知时间
            rule_key = f"{monitor}_{notify}"
            last_time = await get_last_notify_time(rule_key)
            if last_time > 0:
                last_notify = datetime.fromtimestamp(last_time).strftime("%Y-%m-%d %H:%M:%S")
                result += f"  最后通知: {last_notify}\n"
        else:
            result += f"\n规则 {idx}: 格式错误\n"
    
    return result


# 沙盒方法：测试正则表达式
@plugin.mount_sandbox_method(
    method_type=SandboxMethodType.TOOL,
    name="test_regex_pattern",
    description="测试正则表达式模式是否有效"
)
async def test_regex_pattern(_ctx: AgentCtx, pattern: str, test_text: str = "") -> str:
    """测试正则表达式模式
    
    Args:
        pattern: 要测试的正则表达式模式
        test_text: 用于测试的文本（可选）
        
    Returns:
        测试结果
    """
    # 验证正则表达式语法
    if not validate_regex(pattern):
        return f"❌ 正则表达式语法错误: {pattern}"
    
    result = f"✅ 正则表达式语法正确: {pattern}\n"
    
    # 如果提供了测试文本，进行匹配测试
    if test_text.strip():
        try:
            compiled_pattern = re.compile(pattern)
            matches = compiled_pattern.findall(test_text)
            
            if matches:
                result += f"✅ 匹配成功，找到 {len(matches)} 个匹配项:\n"
                for i, match in enumerate(matches[:5], 1):  # 最多显示5个
                    result += f"  {i}. {match}\n"
                if len(matches) > 5:
                    result += f"  ... 还有 {len(matches) - 5} 个匹配项\n"
            else:
                result += "❌ 在测试文本中未找到匹配项\n"
                
        except Exception as e:
            result += f"❌ 匹配测试失败: {e}\n"
    else:
        result += "\n💡 提供测试文本可以验证匹配效果"
    
    return result


# 沙盒方法：添加监听规则（动态添加到存储中）
@plugin.mount_sandbox_method(
    method_type=SandboxMethodType.BEHAVIOR,
    name="add_temp_monitor_rule",
    description="临时添加一条监听规则（重启后失效）"
)
async def add_temp_monitor_rule(
    _ctx: AgentCtx,
    monitor_channel: str,
    keywords: str,
    notify_channel: str
) -> str:
    """临时添加一条监听规则
    
    Args:
        monitor_channel: 要监听的频道
        keywords: 关键词列表，逗号分隔
        notify_channel: 通知目标频道
        
    Returns:
        操作结果
    """
    # 验证输入
    keyword_list = [kw.strip() for kw in keywords.split(',') if kw.strip()]
    if not keyword_list:
        return "错误：关键词列表不能为空"
    
    # 如果当前是正则模式，验证正则表达式
    config = plugin.get_config(KeywordMonitorConfig)
    if config.MATCH_MODE == 2:
        invalid_patterns = [kw for kw in keyword_list if not validate_regex(kw)]
        if invalid_patterns:
            return f"错误：以下正则表达式无效: {', '.join(invalid_patterns)}"
    
    # 存储临时规则
    temp_rules_str = await plugin.store.get(store_key="temp_rules")
    temp_rules = json.loads(temp_rules_str) if temp_rules_str else []
    
    # 构建新规则
    new_rule = f"{monitor_channel}|{keywords}|{notify_channel}"
    
    # 检查是否已存在
    if new_rule in temp_rules:
        return "该规则已存在"
    
    temp_rules.append(new_rule)
    await plugin.store.set(store_key="temp_rules", value=json.dumps(temp_rules))
    
    mode_desc = ["模糊", "精确", "正则"][config.MATCH_MODE]
    return f"✅ 已添加临时规则：监听 {monitor_channel}，关键词 [{keywords}] ({mode_desc}模式)，通知到 {notify_channel}"


# 清理方法
@plugin.mount_cleanup_method()
async def cleanup_plugin():
    """清理插件"""
    core.logger.info(f"插件 '{plugin.name}' 正在清理...")
    core.logger.info(f"插件 '{plugin.name}' 清理完成")
