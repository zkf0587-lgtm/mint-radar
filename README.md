# 打新铸造雷达（云端版）
GitHub Actions 每 10 分钟（北京时间 8:00–次日 1:50）整链扫描 BSC 上 Agent ID 专属铸造，按峰哥纪律过滤，命中才发 Telegram。只读，不签名不交易。
Secrets（Settings → Secrets and variables → Actions）：ANKR_KEY、TG_TOKEN、TG_CHAT_ID。
DEV/合约黑名单：编辑 blacklist.json。手动试跑：Actions → mint-radar → Run workflow。
