# Repair commit context

Commit: `8a1f3cf89ddcc700e25afe42cfad333059adcc94`

Parent: `b5526b780f8b297a76030410b96ba29153afb98f`

## Commit message

### Description

```text
wifi: wlcore: release runtime PM ref on regdomain config failure

wlcore_regdomain_config() gets a runtime PM reference before sending
the regulatory-domain command. When
wlcore_cmd_regdomain_config_locked() fails, the function queues recovery
and returns without dropping that reference.

Release the reference after handling the command result so both success
and failure paths balance the preceding
pm_runtime_resume_and_get(). The recovery worker takes a separate
runtime PM reference and cannot release the reference held here.

Fixes: fa2648a34e73 ("wlcore: Add support for runtime PM")
Cc: stable@vger.kernel.org
Signed-off-by: Runyu Xiao <runyu.xiao@seu.edu.cn>
Link: https://patch.msgid.link/20260820125126.12757-1-runyu.xiao@seu.edu.cn
Signed-off-by: Johannes Berg <johannes.berg@intel.com>
```

## Patch diff

### Historical diff

```diff
diff --git a/drivers/net/wireless/ti/wlcore/main.c b/drivers/net/wireless/ti/wlcore/main.c
index 5595f7a1fc0c..edf6ca23c6c3 100644
--- a/drivers/net/wireless/ti/wlcore/main.c
+++ b/drivers/net/wireless/ti/wlcore/main.c
@@ -3707,44 +3707,42 @@ static void wl1271_op_set_default_key_idx(struct ieee80211_hw *hw,
 	mutex_unlock(&wl->mutex);
 }
 
 void wlcore_regdomain_config(struct wl1271 *wl)
 {
 	int ret;
 
 	if (!(wl->quirks & WLCORE_QUIRK_REGDOMAIN_CONF))
 		return;
 
 	mutex_lock(&wl->mutex);
 
 	if (unlikely(wl->state != WLCORE_STATE_ON))
 		goto out;
 
 	ret = pm_runtime_resume_and_get(wl->dev);
 	if (ret < 0)
 		goto out;
 
 	ret = wlcore_cmd_regdomain_config_locked(wl);
-	if (ret < 0) {
+	if (ret < 0)
 		wl12xx_queue_recovery_work(wl);
-		goto out;
-	}
 
 	pm_runtime_put_autosuspend(wl->dev);
 out:
 	mutex_unlock(&wl->mutex);
 }
 
 static int wl1271_op_hw_scan(struct ieee80211_hw *hw,
 			     struct ieee80211_vif *vif,
 			     struct ieee80211_scan_request *hw_req)
 {
 	struct cfg80211_scan_request *req = &hw_req->req;
 	struct wl1271 *wl = hw->priv;
 	int ret;
 	u8 *ssid = NULL;
 	size_t len = 0;
 
 	wl1271_debug(DEBUG_MAC80211, "mac80211 hw scan");
 
 	if (req->n_ssids) {
 		ssid = req->ssids[0].ssid;

```

## Changed source

### function 'wlcore_regdomain_config' — 'drivers/net/wireless/ti/wlcore/main.c':3710-3735 @ b5526b780f8b297a76030410b96ba29153afb98f (changed function or its pre-fix counterpart)

```c
void wlcore_regdomain_config(struct wl1271 *wl)
{
	int ret;

	if (!(wl->quirks & WLCORE_QUIRK_REGDOMAIN_CONF))
		return;

	mutex_lock(&wl->mutex);

	if (unlikely(wl->state != WLCORE_STATE_ON))
		goto out;

	ret = pm_runtime_resume_and_get(wl->dev);
	if (ret < 0)
		goto out;

	ret = wlcore_cmd_regdomain_config_locked(wl);
	if (ret < 0) {
		wl12xx_queue_recovery_work(wl);
		goto out;
	}

	pm_runtime_put_autosuspend(wl->dev);
out:
	mutex_unlock(&wl->mutex);
}
```

### function 'wlcore_regdomain_config' — 'drivers/net/wireless/ti/wlcore/main.c':3710-3733 @ 8a1f3cf89ddcc700e25afe42cfad333059adcc94 (changed function or its post-fix counterpart)

```c
void wlcore_regdomain_config(struct wl1271 *wl)
{
	int ret;

	if (!(wl->quirks & WLCORE_QUIRK_REGDOMAIN_CONF))
		return;

	mutex_lock(&wl->mutex);

	if (unlikely(wl->state != WLCORE_STATE_ON))
		goto out;

	ret = pm_runtime_resume_and_get(wl->dev);
	if (ret < 0)
		goto out;

	ret = wlcore_cmd_regdomain_config_locked(wl);
	if (ret < 0)
		wl12xx_queue_recovery_work(wl);

	pm_runtime_put_autosuspend(wl->dev);
out:
	mutex_unlock(&wl->mutex);
}
```

## Local supplementary source

### function 'pm_runtime_resume_and_get' — 'include/linux/pm_runtime.h':537-540 @ b5526b780f8b297a76030410b96ba29153afb98f (referenced by changed code: pm_runtime_resume_and_get)

```c
static inline int pm_runtime_resume_and_get(struct device *dev)
{
	return pm_runtime_get_active(dev, 0);
}
```

### function 'pm_runtime_resume_and_get' — 'include/linux/pm_runtime.h':537-540 @ 8a1f3cf89ddcc700e25afe42cfad333059adcc94 (referenced by changed code: pm_runtime_resume_and_get)

```c
static inline int pm_runtime_resume_and_get(struct device *dev)
{
	return pm_runtime_get_active(dev, 0);
}
```

### function 'pm_runtime_get_active' — 'include/linux/pm_runtime.h':516-527 @ b5526b780f8b297a76030410b96ba29153afb98f (one-level callee of pm_runtime_resume_and_get)

```c
static inline int pm_runtime_get_active(struct device *dev, int rpmflags)
{
	int ret;

	ret = __pm_runtime_resume(dev, RPM_GET_PUT | rpmflags);
	if (ret < 0) {
		pm_runtime_put_noidle(dev);
		return ret;
	}

	return 0;
}
```

### function 'pm_runtime_get_active' — 'include/linux/pm_runtime.h':516-527 @ 8a1f3cf89ddcc700e25afe42cfad333059adcc94 (one-level callee of pm_runtime_resume_and_get)

```c
static inline int pm_runtime_get_active(struct device *dev, int rpmflags)
{
	int ret;

	ret = __pm_runtime_resume(dev, RPM_GET_PUT | rpmflags);
	if (ret < 0) {
		pm_runtime_put_noidle(dev);
		return ret;
	}

	return 0;
}
```

### function 'wl12xx_queue_recovery_work' — 'drivers/net/wireless/ti/wlcore/main.c':876-887 @ b5526b780f8b297a76030410b96ba29153afb98f (referenced by changed code: wl12xx_queue_recovery_work)

```c
void wl12xx_queue_recovery_work(struct wl1271 *wl)
{
	/* Avoid a recursive recovery */
/* ... omitted; complete material is in context.json ... */
```

### function 'wl12xx_queue_recovery_work' — 'drivers/net/wireless/ti/wlcore/main.c':876-887 @ 8a1f3cf89ddcc700e25afe42cfad333059adcc94 (referenced by changed code: wl12xx_queue_recovery_work)

```c
void wl12xx_queue_recovery_work(struct wl1271 *wl)
{
	/* Avoid a recursive recovery */
/* ... omitted; complete material is in context.json ... */
```

### macro 'test_bit' — 'include/linux/bitops.h':60-60 @ b5526b780f8b297a76030410b96ba29153afb98f (one-level callee of wl12xx_queue_recovery_work)

```c
#define test_bit(nr, addr)		bitop(_test_bit, nr, addr)
```

### declaration 'ieee80211_queue_work' — 'include/net/mac80211.h':6621-6621 @ b5526b780f8b297a76030410b96ba29153afb98f (one-level callee of wl12xx_queue_recovery_work)

```c
void ieee80211_queue_work(struct ieee80211_hw *hw, struct work_struct *work);
```

### macro 'test_bit' — 'include/linux/bitops.h':60-60 @ 8a1f3cf89ddcc700e25afe42cfad333059adcc94 (one-level callee of wl12xx_queue_recovery_work)

```c
#define test_bit(nr, addr)		bitop(_test_bit, nr, addr)
```

### declaration 'ieee80211_queue_work' — 'include/net/mac80211.h':6621-6621 @ 8a1f3cf89ddcc700e25afe42cfad333059adcc94 (one-level callee of wl12xx_queue_recovery_work)

```c
void ieee80211_queue_work(struct ieee80211_hw *hw, struct work_struct *work);
```

### function 'pm_runtime_put_autosuspend' — 'include/linux/pm_runtime.h':599-603 @ b5526b780f8b297a76030410b96ba29153afb98f (referenced by changed code: pm_runtime_put_autosuspend)

```c
static inline int pm_runtime_put_autosuspend(struct device *dev)
{
	pm_runtime_mark_last_busy(dev);
	return __pm_runtime_put_autosuspend(dev);
}
```

### function 'pm_runtime_put_autosuspend' — 'include/linux/pm_runtime.h':599-603 @ 8a1f3cf89ddcc700e25afe42cfad333059adcc94 (referenced by changed code: pm_runtime_put_autosuspend)

```c
static inline int pm_runtime_put_autosuspend(struct device *dev)
{
	pm_runtime_mark_last_busy(dev);
	return __pm_runtime_put_autosuspend(dev);
}
```

- parse_error: 'C parse errors; extracted spans are best effort'
- parse_error: 'C parse errors; extracted spans are best effort'
- parse_error: 'C parse errors; extracted spans are best effort'
- include_unresolved: 'Cannot resolve asm/module.h'
- parse_error: 'C parse errors; extracted spans are best effort'
- parse_error: 'C parse errors; extracted spans are best effort'
- include_unresolved: 'Cannot resolve asm/bitsperlong.h'
- parse_error: 'C parse errors; extracted spans are best effort'
- include_unresolved: 'Cannot resolve asm/page.h'
- include_unresolved: 'Cannot resolve asm/vmalloc.h'
- parse_error: 'C parse errors; extracted spans are best effort'
- include_unresolved: 'Cannot resolve asm/ptrace.h'
- include_unresolved: 'Cannot resolve asm/irq.h'
- include_unresolved: 'Cannot resolve asm/sections.h'
- parse_error: 'C parse errors; extracted spans are best effort'
- include_unresolved: 'Cannot resolve asm/irq.h'
- include_unresolved: 'Cannot resolve asm/ptrace.h'
- include_unresolved: 'Cannot resolve asm/irq_regs.h'
- include_unresolved: 'Cannot resolve asm/hw_irq.h'
- parse_error: 'C parse errors; extracted spans are best effort'
- parse_error: 'C parse errors; extracted spans are best effort'
- parse_error: 'C parse errors; extracted spans are best effort'
- parse_error: 'C parse errors; extracted spans are best effort'
- parse_error: 'C parse errors; extracted spans are best effort'
- parse_error: 'C parse errors; extracted spans are best effort'
- include_unresolved: 'Cannot resolve asm/barrier.h'
- include_unresolved: 'Cannot resolve asm/stat.h'
- include_unresolved: 'Cannot resolve asm/rwonce.h'
- include_unresolved: 'Cannot resolve asm/cache.h'
- parse_error: 'C parse errors; extracted spans are best effort'
- parse_error: 'C parse errors; extracted spans are best effort'
- parse_error: 'C parse errors; extracted spans are best effort'
- include_unresolved: 'Cannot resolve asm/elf.h'
- parse_error: 'C parse errors; extracted spans are best effort'

## Collection notes

340 diagnostic(s). Full provenance, raw collected material, and diagnostics are in context.json.
