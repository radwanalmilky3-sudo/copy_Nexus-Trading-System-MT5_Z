# AGENT_STATUS.md — حالة الوكيل المحلي (يملؤه OPENCODE)

> ملاحظة: هذا الملف يعكس جهاز المالك المحلي فقط. آخر تحديث يظهر في حقل `updated` أدناه.

```
updated:            # وقت آخر دورة +03:00
agent:              # OpenCode + إصداره إن وجد
machine:            # اسم الجهاز
os:                 # Windows + إصدار
project_dir:        # D:\Nexus-Trading-System-MT5_Z
git_head:           # آخر commit محلي
git_sync:           # clean | ahead | behind | diverged
fleet_local:        # 9000-9008: n/9 على 200 أو not-running
dashboard_local:    # 3100/3000: up | down
redis_local:        # ping: PONG | FAIL
disk_free_gb:       # المساحة الحرة على D:
python_ver:
node_ver:
last_cycle:         # نتيجة آخر دورة 5 دقائق (update + channel)
pending_questions:  # عدد أسئلة مفتوحة في outbox
```
