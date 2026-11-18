# Repair commit context

Commit: `50fd0ada8d37587223001600933270b59cb30e19`

Parent: `1f1d0812f6a8ab8e6f709c599f137c99646512cc`

## Commit message

### Description

```text
gpio: virtuser: skip free_irq when no IRQ is installed

Disabling interrupt monitoring uses atomic_xchg() to clear the stored IRQ.
When monitoring is already disabled, atomic_xchg() returns 0. It must not
be passed to free_irq().

The bug is reproducible on an x86_64 QEMU guest with
CONFIG_GPIO_VIRTUSER=y and CONFIG_GPIO_SIM=y. Configure a live
gpio-virtuser device through configfs. Its input lookup must refer to a
live gpio-sim bank, such as key gpio-sim-test with offset 0. The
consumer's dev_name attribute is shown as <dev> below; then run:

    echo 0 > /sys/kernel/debug/gpio-virtuser/<dev>/gpiod:input:0/interrupts

On an unpatched kernel, this reaches gpio_virtuser_interrupts_set() with
ld->irq still at its initial value 0, and free_irq() reports:

    Trying to free already-free IRQ 0

The same reproducer completes without the warning on the patched kernel.

Fixes: 91581c4b3f29 ("gpio: virtuser: new virtual testing driver for the GPIO API")
Assisted-by: LLM
Signed-off-by: Runyu Xiao <runyu.xiao@seu.edu.cn>
Reviewed-by: Linus Walleij <linusw@kernel.org>
Link: https://patch.msgid.link/20260914051537.15320-1-runyu.xiao@seu.edu.cn
Signed-off-by: Bartosz Golaszewski <bartosz.golaszewski@oss.qualcomm.com>
```

## Patch diff

### Historical diff

```diff
diff --git a/drivers/gpio/gpio-virtuser.c b/drivers/gpio/gpio-virtuser.c
index 7d0d366be37a..d5876c19cfef 100644
--- a/drivers/gpio/gpio-virtuser.c
+++ b/drivers/gpio/gpio-virtuser.c
@@ -675,41 +675,42 @@ static int gpio_virtuser_interrupts_set(void *data, u64 val)
 	if (val > 1)
 		return -EINVAL;
 
 	if (val) {
 		irq = gpiod_to_irq(ld->ad.desc);
 		if (irq < 0)
 			return irq;
 
 		ret = request_threaded_irq(irq, NULL,
 					   gpio_virtuser_irq_handler,
 					   IRQF_TRIGGER_RISING |
 					   IRQF_TRIGGER_FALLING |
 					   IRQF_ONESHOT,
 					   ld->consumer, data);
 		if (ret)
 			return ret;
 
 		atomic_set(&ld->irq, irq);
 	} else {
 		irq = atomic_xchg(&ld->irq, 0);
-		free_irq(irq, ld);
+		if (irq)
+			free_irq(irq, ld);
 	}
 
 	return 0;
 }
 
 DEFINE_DEBUGFS_ATTRIBUTE(gpio_virtuser_interrupts_fops,
 			 gpio_virtuser_interrupts_get,
 			 gpio_virtuser_interrupts_set,
 			 "%llu\n");
 
 static const struct gpio_virtuser_dbgfs_attr_descr
 gpio_virtuser_line_array_dbgfs_attrs[] = {
 	{
 		.name = "values",
 		.fops = &gpio_virtuser_value_array_fops,
 	},
 	{
 		.name = "values_atomic",
 		.fops = &gpio_virtuser_value_array_atomic_fops,
 	},

```

## Changed source

### function 'gpio_virtuser_interrupts_set' — 'drivers/gpio/gpio-virtuser.c':670-699 @ 1f1d0812f6a8ab8e6f709c599f137c99646512cc (changed function or its pre-fix counterpart)

```c
static int gpio_virtuser_interrupts_set(void *data, u64 val)
{
	struct gpio_virtuser_line_data *ld = data;
	int irq, ret;

	if (val > 1)
		return -EINVAL;

	if (val) {
		irq = gpiod_to_irq(ld->ad.desc);
		if (irq < 0)
			return irq;

		ret = request_threaded_irq(irq, NULL,
					   gpio_virtuser_irq_handler,
					   IRQF_TRIGGER_RISING |
					   IRQF_TRIGGER_FALLING |
					   IRQF_ONESHOT,
					   ld->consumer, data);
		if (ret)
			return ret;

		atomic_set(&ld->irq, irq);
	} else {
		irq = atomic_xchg(&ld->irq, 0);
		free_irq(irq, ld);
	}

	return 0;
}
```

### function 'gpio_virtuser_interrupts_set' — 'drivers/gpio/gpio-virtuser.c':670-700 @ 50fd0ada8d37587223001600933270b59cb30e19 (changed function or its post-fix counterpart)

```c
static int gpio_virtuser_interrupts_set(void *data, u64 val)
{
	struct gpio_virtuser_line_data *ld = data;
	int irq, ret;

	if (val > 1)
		return -EINVAL;

	if (val) {
		irq = gpiod_to_irq(ld->ad.desc);
		if (irq < 0)
			return irq;

		ret = request_threaded_irq(irq, NULL,
					   gpio_virtuser_irq_handler,
					   IRQF_TRIGGER_RISING |
					   IRQF_TRIGGER_FALLING |
					   IRQF_ONESHOT,
					   ld->consumer, data);
		if (ret)
			return ret;

		atomic_set(&ld->irq, irq);
	} else {
		irq = atomic_xchg(&ld->irq, 0);
		if (irq)
			free_irq(irq, ld);
	}

	return 0;
}
```

## Local supplementary source

### function 'gpiod_to_irq' — 'include/linux/gpio/consumer.h':519-524 @ 1f1d0812f6a8ab8e6f709c599f137c99646512cc (referenced by changed code: gpiod_to_irq)

```c
static inline int gpiod_to_irq(const struct gpio_desc *desc)
{
	/* GPIO can never have been requested */
	WARN_ON(desc);
	return -EINVAL;
}
```

### function 'gpiod_to_irq' — 'include/linux/gpio/consumer.h':519-524 @ 50fd0ada8d37587223001600933270b59cb30e19 (referenced by changed code: gpiod_to_irq)

```c
static inline int gpiod_to_irq(const struct gpio_desc *desc)
{
	/* GPIO can never have been requested */
	WARN_ON(desc);
	return -EINVAL;
}
```

### declaration 'request_threaded_irq' — 'include/linux/interrupt.h':154-157 @ 1f1d0812f6a8ab8e6f709c599f137c99646512cc (referenced by changed code: request_threaded_irq)

```c
extern int __must_check
request_threaded_irq(unsigned int irq, irq_handler_t handler,
		     irq_handler_t thread_fn,
		     unsigned long flags, const char *name, void *dev);
```

### declaration 'request_threaded_irq' — 'include/linux/interrupt.h':154-157 @ 50fd0ada8d37587223001600933270b59cb30e19 (referenced by changed code: request_threaded_irq)

```c
extern int __must_check
request_threaded_irq(unsigned int irq, irq_handler_t handler,
		     irq_handler_t thread_fn,
		     unsigned long flags, const char *name, void *dev);
```

### function 'atomic_set' — 'include/linux/atomic/atomic-instrumented.h':64-69 @ 1f1d0812f6a8ab8e6f709c599f137c99646512cc (referenced by changed code: atomic_set)

```c
static __always_inline void
atomic_set(atomic_t *v, int i)
{
	instrument_atomic_write(v, sizeof(*v));
	raw_atomic_set(v, i);
}
```

### function 'atomic_set' — 'include/linux/atomic/atomic-instrumented.h':64-69 @ 50fd0ada8d37587223001600933270b59cb30e19 (referenced by changed code: atomic_set)

```c
static __always_inline void
atomic_set(atomic_t *v, int i)
{
	instrument_atomic_write(v, sizeof(*v));
	raw_atomic_set(v, i);
}
```

### function 'instrument_atomic_write' — 'include/linux/instrumented.h':95-100 @ 1f1d0812f6a8ab8e6f709c599f137c99646512cc (one-level callee of atomic_set)

```c
static __always_inline void instrument_atomic_write(const volatile void *v, size_t size)
{
	kasan_check_write(v, size);
	kcsan_check_atomic_write(v, size);
	instrument_atomic_check_alignment(v, size);
}
```

### function 'raw_atomic_set' — 'include/linux/atomic/atomic-arch-fallback.h':500-504 @ 1f1d0812f6a8ab8e6f709c599f137c99646512cc (one-level callee of atomic_set)

```c
static __always_inline void
raw_atomic_set(atomic_t *v, int i)
{
	arch_atomic_set(v, i);
}
```

### function 'instrument_atomic_write' — 'include/linux/instrumented.h':95-100 @ 50fd0ada8d37587223001600933270b59cb30e19 (one-level callee of atomic_set)

```c
static __always_inline void instrument_atomic_write(const volatile void *v, size_t size)
{
	kasan_check_write(v, size);
	kcsan_check_atomic_write(v, size);
	instrument_atomic_check_alignment(v, size);
}
```

### function 'raw_atomic_set' — 'include/linux/atomic/atomic-arch-fallback.h':500-504 @ 50fd0ada8d37587223001600933270b59cb30e19 (one-level callee of atomic_set)

```c
static __always_inline void
raw_atomic_set(atomic_t *v, int i)
{
	arch_atomic_set(v, i);
}
```

### function 'atomic_xchg' — 'include/linux/atomic/atomic-instrumented.h':1115-1121 @ 1f1d0812f6a8ab8e6f709c599f137c99646512cc (referenced by changed code: atomic_xchg)

```c
static __always_inline int
atomic_xchg(atomic_t *v, int new)
{
	kcsan_mb();
	instrument_atomic_read_write(v, sizeof(*v));
	return raw_atomic_xchg(v, new);
}
```

### function 'atomic_xchg' — 'include/linux/atomic/atomic-instrumented.h':1115-1121 @ 50fd0ada8d37587223001600933270b59cb30e19 (referenced by changed code: atomic_xchg)

```c
static __always_inline int
atomic_xchg(atomic_t *v, int new)
{
	kcsan_mb();
	instrument_atomic_read_write(v, sizeof(*v));
	return raw_atomic_xchg(v, new);
}
```

- parse_error: 'C parse errors; extracted spans are best effort'
- parse_error: 'C parse errors; extracted spans are best effort'
- parse_error: 'C parse errors; extracted spans are best effort'
- include_unresolved: 'Cannot resolve asm/atomic.h'
- include_unresolved: 'Cannot resolve asm/barrier.h'
- parse_error: 'C parse errors; extracted spans are best effort'
- parse_error: 'C parse errors; extracted spans are best effort'
- parse_error: 'C parse errors; extracted spans are best effort'
- parse_error: 'C parse errors; extracted spans are best effort'
- parse_error: 'C parse errors; extracted spans are best effort'
- include_unresolved: 'Cannot resolve asm/device.h'
- parse_error: 'C parse errors; extracted spans are best effort'
- include_unresolved: 'Cannot resolve asm/errno.h'
- parse_error: 'C parse errors; extracted spans are best effort'
- parse_error: 'C parse errors; extracted spans are best effort'
- parse_error: 'C parse errors; extracted spans are best effort'
- include_unresolved: 'Cannot resolve asm/ptrace.h'
- include_unresolved: 'Cannot resolve asm/irq.h'
- include_unresolved: 'Cannot resolve asm/sections.h'
- include_unresolved: 'Cannot resolve asm/irq_work.h'
- parse_error: 'C parse errors; extracted spans are best effort'
- include_unresolved: 'Cannot resolve asm/barrier.h'
- parse_error: 'C parse errors; extracted spans are best effort'
- include_unresolved: 'Cannot resolve asm/percpu.h'
- parse_error: 'C parse errors; extracted spans are best effort'
- include_unresolved: 'Cannot resolve asm/module.h'
- parse_error: 'C parse errors; extracted spans are best effort'
- include_unresolved: 'Cannot resolve asm/current.h'
- include_unresolved: 'Cannot resolve asm/processor.h'
- parse_error: 'C parse errors; extracted spans are best effort'
- parse_error: 'C parse errors; extracted spans are best effort'
- include_unresolved: 'Cannot resolve asm/byteorder.h'
- include_unresolved: 'Cannot resolve asm/prom.h'

## Collection notes

269 diagnostic(s). Full provenance, raw collected material, and diagnostics are in context.json.
