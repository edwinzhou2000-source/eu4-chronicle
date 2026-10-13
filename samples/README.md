# 样例说明

本目录为**脱敏最小合成** `.eu4` 文本，不是真实游戏导出。

| 文件 | 含义 |
|------|------|
| `byz_1444.eu4` | 拜占庭开局附近：与瓦拉几亚同盟、对奥斯曼宿敌 |
| `byz_1453.eu4` | 后期：断盟、吞并省份 317、附庸 ATH、AE 上升、进行中战争 |

演示：

```bash
uv run eu4-game-report analyze --prev samples/byz_1444.eu4 --curr samples/byz_1453.eu4 --mode mock
```
