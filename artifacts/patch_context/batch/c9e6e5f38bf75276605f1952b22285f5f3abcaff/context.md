# Repair commit context

Commit: `c9e6e5f38bf75276605f1952b22285f5f3abcaff`

Parent: `5ab3dc647751996784cff20a51f3730f4e88afe4`

## Commit message

### Description

```text
ALSA: hda: trace PCM open only after assigning a stream

Stream assignment can fail when hardware streams are exhausted.
Move the tracepoint after the NULL check because its payload accesses
the assigned stream tag.

Detected by static analysis and reviewed with AI-assisted source auditing.

Fixes: 184865085b88 ("ALSA: hda - rename hda_intel_trace.h to hda_controller_trace.h")
Assisted-by: LLM
Signed-off-by: Slavin Liu <bolin.liu@seu.edu.cn>
Link: https://patch.msgid.link/20260913125154.109944-1-bolin.liu@seu.edu.cn
Signed-off-by: Takashi Iwai <tiwai@suse.de>
```

## Patch diff

### Historical diff

```diff
diff --git a/sound/hda/common/controller.c b/sound/hda/common/controller.c
index afec5c5546ec..18dae022b324 100644
--- a/sound/hda/common/controller.c
+++ b/sound/hda/common/controller.c
@@ -569,45 +569,45 @@ static const struct snd_pcm_hardware azx_pcm_hw = {
 	.period_bytes_min =	128,
 	.period_bytes_max =	AZX_MAX_BUF_SIZE / 2,
 	.periods_min =		2,
 	.periods_max =		AZX_MAX_FRAG,
 	.fifo_size =		0,
 };
 
 static int azx_pcm_open(struct snd_pcm_substream *substream)
 {
 	struct azx_pcm *apcm = snd_pcm_substream_chip(substream);
 	struct hda_pcm_stream *hinfo = to_hda_pcm_stream(substream);
 	struct azx *chip = apcm->chip;
 	struct azx_dev *azx_dev;
 	struct snd_pcm_runtime *runtime = substream->runtime;
 	int err;
 	int buff_step;
 
 	snd_hda_codec_pcm_get(apcm->info);
 	mutex_lock(&chip->open_mutex);
 	azx_dev = azx_assign_device(chip, substream);
-	trace_azx_pcm_open(chip, azx_dev);
 	if (azx_dev == NULL) {
 		err = -EBUSY;
 		goto unlock;
 	}
+	trace_azx_pcm_open(chip, azx_dev);
 	runtime->private_data = azx_dev;
 
 	runtime->hw = azx_pcm_hw;
 	if (chip->gts_present)
 		runtime->hw.info |= SNDRV_PCM_INFO_HAS_LINK_SYNCHRONIZED_ATIME;
 	runtime->hw.channels_min = hinfo->channels_min;
 	runtime->hw.channels_max = hinfo->channels_max;
 	runtime->hw.formats = hinfo->formats;
 	runtime->hw.rates = hinfo->rates;
 	snd_pcm_limit_hw_rates(runtime);
 	snd_pcm_hw_constraint_integer(runtime, SNDRV_PCM_HW_PARAM_PERIODS);
 
 	/* avoid wrap-around with wall-clock */
 	snd_pcm_hw_constraint_minmax(runtime, SNDRV_PCM_HW_PARAM_BUFFER_TIME,
 				     20,
 				     178000000);
 
 	if (chip->align_buffer_size)
 		/* constrain buffer sizes to be multiple of 128
 		   bytes. This is more efficient in terms of memory

```

## Changed source

### function 'azx_pcm_open' — 'sound/hda/common/controller.c':576-669 @ 5ab3dc647751996784cff20a51f3730f4e88afe4 (changed function or its pre-fix counterpart)

```c
static int azx_pcm_open(struct snd_pcm_substream *substream)
{
	struct azx_pcm *apcm = snd_pcm_substream_chip(substream);
	struct hda_pcm_stream *hinfo = to_hda_pcm_stream(substream);
	struct azx *chip = apcm->chip;
	struct azx_dev *azx_dev;
	struct snd_pcm_runtime *runtime = substream->runtime;
	int err;
	int buff_step;

	snd_hda_codec_pcm_get(apcm->info);
	mutex_lock(&chip->open_mutex);
	azx_dev = azx_assign_device(chip, substream);
	trace_azx_pcm_open(chip, azx_dev);
	if (azx_dev == NULL) {
		err = -EBUSY;
		goto unlock;
	}
	runtime->private_data = azx_dev;

	runtime->hw = azx_pcm_hw;
	if (chip->gts_present)
		runtime->hw.info |= SNDRV_PCM_INFO_HAS_LINK_SYNCHRONIZED_ATIME;
	runtime->hw.channels_min = hinfo->channels_min;
	runtime->hw.channels_max = hinfo->channels_max;
	runtime->hw.formats = hinfo->formats;
	runtime->hw.rates = hinfo->rates;
	snd_pcm_limit_hw_rates(runtime);
	snd_pcm_hw_constraint_integer(runtime, SNDRV_PCM_HW_PARAM_PERIODS);

	/* avoid wrap-around with wall-clock */
	snd_pcm_hw_constraint_minmax(runtime, SNDRV_PCM_HW_PARAM_BUFFER_TIME,
				     20,
				     178000000);

	if (chip->align_buffer_size)
		/* constrain buffer sizes to be multiple of 128
		   bytes. This is more efficient in terms of memory
		   access but isn't required by the HDA spec and
		   prevents users from specifying exact period/buffer
		   sizes. For example for 44.1kHz, a period size set
		   to 20ms will be rounded to 19.59ms. */
		buff_step = 128;
	else
		/* Don't enforce steps on buffer sizes, still need to
		   be multiple of 4 bytes (HDA spec). Tested on Intel
		   HDA controllers, may not work on all devices where
		   option needs to be disabled */
		buff_step = 4;

	snd_pcm_hw_constraint_step(runtime, 0, SNDRV_PCM_HW_PARAM_BUFFER_BYTES,
				   buff_step);
	snd_pcm_hw_constraint_step(runtime, 0, SNDRV_PCM_HW_PARAM_PERIOD_BYTES,
				   buff_step);
	snd_hda_power_up(apcm->codec);
	if (hinfo->ops.open)
		err = hinfo->ops.open(hinfo, apcm->codec, substream);
	else
		err = -ENODEV;
	if (err < 0) {
		azx_release_device(azx_dev);
		goto powerdown;
	}
	snd_pcm_limit_hw_rates(runtime);
	/* sanity check */
	if (snd_BUG_ON(!runtime->hw.channels_min) ||
	    snd_BUG_ON(!runtime->hw.channels_max) ||
	    snd_BUG_ON(!runtime->hw.formats) ||
	    snd_BUG_ON(!runtime->hw.rates)) {
		azx_release_device(azx_dev);
		if (hinfo->ops.close)
			hinfo->ops.close(hinfo, apcm->codec, substream);
		err = -EINVAL;
		goto powerdown;
	}

	/* disable LINK_ATIME timestamps for capture streams
	   until we figure out how to handle digital inputs */
	if (substream->stream == SNDRV_PCM_STREAM_CAPTURE) {
		runtime->hw.info &= ~SNDRV_PCM_INFO_HAS_WALL_CLOCK; /* legacy */
		runtime->hw.info &= ~SNDRV_PCM_INFO_HAS_LINK_ATIME;
	}

	snd_pcm_set_sync(substream);
	mutex_unlock(&chip->open_mutex);
	return 0;

 powerdown:
	snd_hda_power_down(apcm->codec);
 unlock:
	mutex_unlock(&chip->open_mutex);
	snd_hda_codec_pcm_put(apcm->info);
	return err;
}
```

### function 'azx_pcm_open' — 'sound/hda/common/controller.c':576-669 @ c9e6e5f38bf75276605f1952b22285f5f3abcaff (changed function or its post-fix counterpart)

```c
static int azx_pcm_open(struct snd_pcm_substream *substream)
{
	struct azx_pcm *apcm = snd_pcm_substream_chip(substream);
	struct hda_pcm_stream *hinfo = to_hda_pcm_stream(substream);
	struct azx *chip = apcm->chip;
	struct azx_dev *azx_dev;
	struct snd_pcm_runtime *runtime = substream->runtime;
	int err;
	int buff_step;

	snd_hda_codec_pcm_get(apcm->info);
	mutex_lock(&chip->open_mutex);
	azx_dev = azx_assign_device(chip, substream);
	if (azx_dev == NULL) {
		err = -EBUSY;
		goto unlock;
	}
	trace_azx_pcm_open(chip, azx_dev);
	runtime->private_data = azx_dev;

	runtime->hw = azx_pcm_hw;
	if (chip->gts_present)
		runtime->hw.info |= SNDRV_PCM_INFO_HAS_LINK_SYNCHRONIZED_ATIME;
	runtime->hw.channels_min = hinfo->channels_min;
	runtime->hw.channels_max = hinfo->channels_max;
	runtime->hw.formats = hinfo->formats;
	runtime->hw.rates = hinfo->rates;
	snd_pcm_limit_hw_rates(runtime);
	snd_pcm_hw_constraint_integer(runtime, SNDRV_PCM_HW_PARAM_PERIODS);

	/* avoid wrap-around with wall-clock */
	snd_pcm_hw_constraint_minmax(runtime, SNDRV_PCM_HW_PARAM_BUFFER_TIME,
				     20,
				     178000000);

	if (chip->align_buffer_size)
		/* constrain buffer sizes to be multiple of 128
		   bytes. This is more efficient in terms of memory
		   access but isn't required by the HDA spec and
		   prevents users from specifying exact period/buffer
		   sizes. For example for 44.1kHz, a period size set
		   to 20ms will be rounded to 19.59ms. */
		buff_step = 128;
	else
		/* Don't enforce steps on buffer sizes, still need to
		   be multiple of 4 bytes (HDA spec). Tested on Intel
		   HDA controllers, may not work on all devices where
		   option needs to be disabled */
		buff_step = 4;

	snd_pcm_hw_constraint_step(runtime, 0, SNDRV_PCM_HW_PARAM_BUFFER_BYTES,
				   buff_step);
	snd_pcm_hw_constraint_step(runtime, 0, SNDRV_PCM_HW_PARAM_PERIOD_BYTES,
				   buff_step);
	snd_hda_power_up(apcm->codec);
	if (hinfo->ops.open)
		err = hinfo->ops.open(hinfo, apcm->codec, substream);
	else
		err = -ENODEV;
	if (err < 0) {
		azx_release_device(azx_dev);
		goto powerdown;
	}
	snd_pcm_limit_hw_rates(runtime);
	/* sanity check */
	if (snd_BUG_ON(!runtime->hw.channels_min) ||
	    snd_BUG_ON(!runtime->hw.channels_max) ||
	    snd_BUG_ON(!runtime->hw.formats) ||
	    snd_BUG_ON(!runtime->hw.rates)) {
		azx_release_device(azx_dev);
		if (hinfo->ops.close)
			hinfo->ops.close(hinfo, apcm->codec, substream);
		err = -EINVAL;
		goto powerdown;
	}

	/* disable LINK_ATIME timestamps for capture streams
	   until we figure out how to handle digital inputs */
	if (substream->stream == SNDRV_PCM_STREAM_CAPTURE) {
		runtime->hw.info &= ~SNDRV_PCM_INFO_HAS_WALL_CLOCK; /* legacy */
		runtime->hw.info &= ~SNDRV_PCM_INFO_HAS_LINK_ATIME;
	}

	snd_pcm_set_sync(substream);
	mutex_unlock(&chip->open_mutex);
	return 0;

 powerdown:
	snd_hda_power_down(apcm->codec);
 unlock:
	mutex_unlock(&chip->open_mutex);
	snd_hda_codec_pcm_put(apcm->info);
	return err;
}
```

## Local supplementary source

### macro 'snd_pcm_substream_chip' — 'include/sound/pcm.h':21-21 @ 5ab3dc647751996784cff20a51f3730f4e88afe4 (referenced by changed code: snd_pcm_substream_chip)

```c
#define snd_pcm_substream_chip(substream) ((substream)->private_data)
```

### macro 'snd_pcm_substream_chip' — 'include/sound/pcm.h':21-21 @ c9e6e5f38bf75276605f1952b22285f5f3abcaff (referenced by changed code: snd_pcm_substream_chip)

```c
#define snd_pcm_substream_chip(substream) ((substream)->private_data)
```

### function 'to_hda_pcm_stream' — 'sound/hda/common/controller.c':60-65 @ 5ab3dc647751996784cff20a51f3730f4e88afe4 (referenced by changed code: to_hda_pcm_stream)

```c
static inline struct hda_pcm_stream *
to_hda_pcm_stream(struct snd_pcm_substream *substream)
{
	struct azx_pcm *apcm = snd_pcm_substream_chip(substream);
	return &apcm->info->stream[substream->stream];
}
```

### function 'to_hda_pcm_stream' — 'sound/hda/common/controller.c':60-65 @ c9e6e5f38bf75276605f1952b22285f5f3abcaff (referenced by changed code: to_hda_pcm_stream)

```c
static inline struct hda_pcm_stream *
to_hda_pcm_stream(struct snd_pcm_substream *substream)
{
	struct azx_pcm *apcm = snd_pcm_substream_chip(substream);
	return &apcm->info->stream[substream->stream];
}
```

### function 'snd_hda_codec_pcm_get' — 'include/sound/hda_codec.h':440-443 @ 5ab3dc647751996784cff20a51f3730f4e88afe4 (referenced by changed code: snd_hda_codec_pcm_get)

```c
static inline void snd_hda_codec_pcm_get(struct hda_pcm *pcm)
{
	snd_refcount_get(&pcm->codec->pcm_ref);
}
```

### function 'snd_hda_codec_pcm_get' — 'include/sound/hda_codec.h':440-443 @ c9e6e5f38bf75276605f1952b22285f5f3abcaff (referenced by changed code: snd_hda_codec_pcm_get)

```c
static inline void snd_hda_codec_pcm_get(struct hda_pcm *pcm)
{
	snd_refcount_get(&pcm->codec->pcm_ref);
}
```

### function 'snd_refcount_get' — 'include/sound/core.h':91-94 @ 5ab3dc647751996784cff20a51f3730f4e88afe4 (one-level callee of snd_hda_codec_pcm_get)

```c
static inline void snd_refcount_get(struct snd_refcount *ref)
{
	atomic_inc(&ref->count);
}
```

### function 'snd_refcount_get' — 'include/sound/core.h':91-94 @ c9e6e5f38bf75276605f1952b22285f5f3abcaff (one-level callee of snd_hda_codec_pcm_get)

```c
static inline void snd_refcount_get(struct snd_refcount *ref)
{
	atomic_inc(&ref->count);
}
```

### function 'azx_assign_device' — 'sound/hda/common/controller.c':43-52 @ 5ab3dc647751996784cff20a51f3730f4e88afe4 (referenced by changed code: azx_assign_device)

```c
static inline struct azx_dev *
azx_assign_device(struct azx *chip, struct snd_pcm_substream *substream)
{
	struct hdac_stream *s;

	s = snd_hdac_stream_assign(azx_bus(chip), substream);
	if (!s)
		return NULL;
	return stream_to_azx_dev(s);
}
```

### function 'azx_assign_device' — 'sound/hda/common/controller.c':43-52 @ c9e6e5f38bf75276605f1952b22285f5f3abcaff (referenced by changed code: azx_assign_device)

```c
static inline struct azx_dev *
azx_assign_device(struct azx *chip, struct snd_pcm_substream *substream)
{
	struct hdac_stream *s;

	s = snd_hdac_stream_assign(azx_bus(chip), substream);
	if (!s)
		return NULL;
	return stream_to_azx_dev(s);
}
```

### macro 'azx_bus' — 'sound/hda/common/hda_controller.h':152-152 @ 5ab3dc647751996784cff20a51f3730f4e88afe4 (one-level callee of azx_assign_device)

```c
#define azx_bus(chip)	(&(chip)->bus.core)
```

### macro 'stream_to_azx_dev' — 'sound/hda/common/hda_controller.h':69-69 @ 5ab3dc647751996784cff20a51f3730f4e88afe4 (one-level callee of azx_assign_device)

```c
#define stream_to_azx_dev(s)	container_of(s, struct azx_dev, core)
```

- parse_error: 'C parse errors; extracted spans are best effort'
- parse_error: 'C parse errors; extracted spans are best effort'
- include_unresolved: 'Cannot resolve asm/tsc.h'
- parse_error: 'C parse errors; extracted spans are best effort'
- include_unresolved: 'Cannot resolve asm/div64.h'
- include_unresolved: 'Cannot resolve asm/io.h'
- include_unresolved: 'Cannot resolve asm/clocksource.h'
- include_unresolved: 'Cannot resolve asm/delay.h'
- parse_error: 'C parse errors; extracted spans are best effort'
- include_unresolved: 'Cannot resolve asm/ptrace.h'
- include_unresolved: 'Cannot resolve asm/irq.h'
- include_unresolved: 'Cannot resolve asm/sections.h'
- parse_error: 'C parse errors; extracted spans are best effort'
- include_unresolved: 'Cannot resolve asm/byteorder.h'
- parse_error: 'C parse errors; extracted spans are best effort'
- include_unresolved: 'Cannot resolve asm/module.h'
- parse_error: 'C parse errors; extracted spans are best effort'
- parse_error: 'C parse errors; extracted spans are best effort'
- parse_error: 'C parse errors; extracted spans are best effort'
- parse_error: 'C parse errors; extracted spans are best effort'
- parse_error: 'C parse errors; extracted spans are best effort'
- parse_error: 'C parse errors; extracted spans are best effort'
- include_unresolved: 'Cannot resolve linux/param.h'
- include_unresolved: 'Cannot resolve asm/timex.h'
- parse_error: 'C parse errors; extracted spans are best effort'
- parse_error: 'C parse errors; extracted spans are best effort'
- include_unresolved: 'Cannot resolve asm/barrier.h'
- include_unresolved: 'Cannot resolve asm/cache.h'
- parse_error: 'C parse errors; extracted spans are best effort'
- parse_error: 'C parse errors; extracted spans are best effort'
- include_unresolved: 'Cannot resolve asm/byteorder.h'
- include_unresolved: 'Cannot resolve asm/prom.h'
- include_unresolved: 'Cannot resolve asm/vdso/clocksource.h'
- parse_error: 'C parse errors; extracted spans are best effort'

## Collection notes

311 diagnostic(s). Full provenance, raw collected material, and diagnostics are in context.json.
