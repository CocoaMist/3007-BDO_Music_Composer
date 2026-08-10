// Experimental bounded native mixer for Python/C++ differential validation.
//
// This file deliberately owns no BDO/editor model. Python submits an immutable
// playback projection during preload; the render call performs no allocation,
// file I/O, logging, or callbacks into Python.

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <new>
#include <vector>

#if defined(_WIN32)
#define BDO_AUDIO_API extern "C" __declspec(dllexport)
#else
#define BDO_AUDIO_API extern "C"
#endif

namespace {

constexpr std::uint32_t kAbiVersion = 1;
constexpr std::uint64_t kCapabilityBasicStereoMix = 1ULL << 0;
constexpr std::uint64_t kCapabilityExactFrameScheduling = 1ULL << 1;
constexpr std::uint64_t kCapabilitySeek = 1ULL << 2;
constexpr std::uint64_t kCapabilitySampleLoop = 1ULL << 3;
constexpr std::uint64_t kCapabilityBoundedVoices = 1ULL << 4;
constexpr std::uint64_t kCapabilityVoiceEnvelope = 1ULL << 5;
constexpr std::uint64_t kCapabilityArticulationEnvelope = 1ULL << 6;
constexpr std::uint64_t kCapabilityMasterLimiter = 1ULL << 7;
constexpr double kPi = 3.14159265358979323846;
constexpr float kMasterTargetPeak = 0.90F;
constexpr float kOutputLimitThreshold = 0.95F;

struct Sample {
    std::vector<float> pcm;
    std::int64_t frames = 0;
};

struct Event {
    std::int64_t frame = 0;
    std::int32_t sample_index = -1;
    double ratio = 1.0;
    float gain = 1.0F;
    std::int64_t duration_frames = 0;
    std::int64_t loop_start_frame = -1;
    std::int64_t loop_end_frame = -1;
    std::int64_t audible_frames = 0;
    std::int64_t fade_in_frames = 0;
    std::int64_t fade_out_frames = 0;
    std::int32_t instrument_id = 0;
    std::int32_t ntype = 0;
    bool native_articulation = false;
    std::uint64_t serial = 0;
};

struct Voice {
    std::int32_t sample_index = -1;
    double position = 0.0;
    double ratio = 1.0;
    float gain = 1.0F;
    std::int64_t age_frames = 0;
    std::int64_t remaining_frames = 0;
    std::int64_t audible_frames = 0;
    std::int64_t fade_in_frames = 0;
    std::int64_t fade_out_frames = 0;
    std::int64_t duration_frames = 0;
    std::int32_t instrument_id = 0;
    std::int32_t ntype = 0;
    bool native_articulation = false;
    std::int64_t loop_start_frame = -1;
    std::int64_t loop_end_frame = -1;
    std::uint64_t serial = 0;
};

struct Mixer {
    explicit Mixer(std::int32_t rate, std::int32_t voice_limit)
        : sample_rate(std::max<std::int32_t>(1, rate)),
          max_voices(std::clamp<std::int32_t>(voice_limit, 1, 256)) {
        voices.reserve(static_cast<std::size_t>(max_voices));
    }

    std::int32_t sample_rate;
    std::int32_t max_voices;
    std::vector<Sample> samples;
    std::vector<Event> events;
    std::vector<Voice> voices;
    std::int64_t frame = 0;
    std::size_t event_index = 0;
    std::uint64_t next_serial = 0;
    std::uint64_t voice_steals = 0;
    float master_gain = 1.0F;
    bool finalised = false;
};

bool valid_loop(const Voice& voice, const Sample& sample) {
    return voice.loop_start_frame >= 0
        && voice.loop_end_frame > voice.loop_start_frame
        && voice.loop_end_frame <= sample.frames;
}

void wrap_position(Voice& voice, const Sample& sample) {
    if (!valid_loop(voice, sample)
        || voice.position < static_cast<double>(voice.loop_end_frame)) {
        return;
    }
    const double span = static_cast<double>(
        voice.loop_end_frame - voice.loop_start_frame
    );
    voice.position = static_cast<double>(voice.loop_start_frame)
        + std::fmod(
            voice.position - static_cast<double>(voice.loop_start_frame),
            span
        );
}

void start_voice(Mixer& mixer, const Event& event, std::int64_t age) {
    if (event.sample_index < 0
        || static_cast<std::size_t>(event.sample_index) >= mixer.samples.size()
        || age < 0
        || age >= event.audible_frames) {
        return;
    }
    if (mixer.voices.size() >= static_cast<std::size_t>(mixer.max_voices)) {
        mixer.voices.erase(mixer.voices.begin());
        ++mixer.voice_steals;
    }
    Voice voice;
    voice.sample_index = event.sample_index;
    voice.position = static_cast<double>(age) * event.ratio;
    voice.ratio = event.ratio;
    voice.gain = event.gain;
    voice.age_frames = age;
    voice.remaining_frames = event.audible_frames - age;
    voice.audible_frames = event.audible_frames;
    voice.fade_in_frames = event.fade_in_frames;
    voice.fade_out_frames = event.fade_out_frames;
    voice.duration_frames = event.duration_frames;
    voice.instrument_id = event.instrument_id;
    voice.ntype = event.ntype;
    voice.native_articulation = event.native_articulation;
    voice.loop_start_frame = event.loop_start_frame;
    voice.loop_end_frame = event.loop_end_frame;
    voice.serial = event.serial;
    wrap_position(voice, mixer.samples[static_cast<std::size_t>(voice.sample_index)]);
    mixer.voices.push_back(voice);
}

float articulation_gain(const Voice& voice, std::int32_t sample_rate) {
    const std::int32_t value = voice.ntype;
    if (voice.native_articulation || value == 0 || value == 9
        || value == 10 || value == 99) {
        return 1.0F;
    }
    const double duration = static_cast<double>(
        std::max<std::int64_t>(1, voice.duration_frames)
    );
    const double age = static_cast<double>(voice.age_frames);
    const double progress = std::clamp(age / duration, 0.0, 1.0);
    auto sine = [&](double frequency) {
        return std::sin(age * 2.0 * kPi * frequency
            / static_cast<double>(std::max<std::int32_t>(1, sample_rate)));
    };
    if (value == 1 && voice.instrument_id != 0x1C && voice.instrument_id != 0x20) {
        return static_cast<float>(1.06 - 0.06 * progress);
    }
    if (value == 2) return static_cast<float>(1.08 - 0.18 * progress);
    if (value == 3 || value == 23) {
        return static_cast<float>(0.48 + 0.52 * std::min(1.0, progress * 3.0));
    }
    if (value == 12) return static_cast<float>(1.0 - 0.42 * progress);
    if (value == 13) return static_cast<float>(0.58 * std::exp(-3.0 * progress));
    if (value == 14) return 0.70F;
    if (value == 15) {
        const double phase = std::fmod(progress * 3.0, 1.0);
        return static_cast<float>(std::clamp((0.84 - phase) / 0.12, 0.0, 1.0));
    }
    if (value == 16) return static_cast<float>(0.55 + 0.45 * std::sin(progress * kPi));
    if (value == 11) return static_cast<float>(0.90 + 0.10 * std::min(1.0, progress * 1.5));
    if (value == 20) return static_cast<float>(0.68 + 0.22 * sine(1.3));
    if (value == 21) return static_cast<float>(0.78 + 0.18 * sine(2.1));
    if (value == 22) return static_cast<float>(1.22 * std::exp(-5.5 * progress));
    if (value == 24) {
        const double wave = sine(38.0);
        const double sign = wave > 0.0 ? 1.0 : (wave < 0.0 ? -1.0 : 0.0);
        return static_cast<float>(0.55 + 0.45 * sign);
    }
    if (value == 25) return static_cast<float>(0.72 + 0.28 * sine(13.0));
    if (value == 26) return 0.62F;
    if (value == 27) return 0.82F;
    if (value == 28) return 1.08F;
    double frequency = 0.0;
    double depth = 0.0;
    switch (value) {
        case 4: frequency = 5.0; depth = 0.22; break;
        case 5: frequency = 6.0; depth = 0.24; break;
        case 6: frequency = 5.5; depth = 0.14; break;
        case 7: frequency = 7.0; depth = 0.18; break;
        case 8: frequency = 8.0; depth = 0.22; break;
        case 17: frequency = 9.0; depth = 0.16; break;
        case 18: frequency = 6.5; depth = 0.28; break;
        case 19: frequency = 11.0; depth = 0.14; break;
        default: return 1.0F;
    }
    return static_cast<float>(1.0 - depth * 0.5 + sine(frequency) * depth * 0.5);
}

float soft_limit(float value) {
    const float magnitude = std::abs(value);
    if (magnitude <= kOutputLimitThreshold) {
        return value;
    }
    const float excess = magnitude - kOutputLimitThreshold;
    const float compressed = kOutputLimitThreshold
        + excess / (1.0F + excess / (1.0F - kOutputLimitThreshold));
    return std::copysign(compressed, value);
}

void apply_master_output(Mixer& mixer, float* output, std::int32_t frames) {
    float raw_peak = 0.0F;
    for (std::int32_t index = 0; index < frames * 2; ++index) {
        raw_peak = std::max(raw_peak, std::abs(output[index]));
    }
    const float target_gain = raw_peak > 1.0e-9F
        ? std::min(1.0F, kMasterTargetPeak / raw_peak)
        : 1.0F;
    const float start_gain = mixer.master_gain;
    float end_gain = target_gain;
    std::int32_t transition_frames = frames;
    if (target_gain < start_gain) {
        transition_frames = std::min(
            frames,
            std::max(1, static_cast<std::int32_t>(
                std::lround(static_cast<double>(mixer.sample_rate) * 0.003)
            ))
        );
    } else {
        const double release_frames = std::max(
            1.0,
            static_cast<double>(mixer.sample_rate) * 0.240
        );
        const double release_amount = 1.0
            - std::exp(-static_cast<double>(frames) / release_frames);
        end_gain = start_gain
            + (target_gain - start_gain) * static_cast<float>(release_amount);
    }
    for (std::int32_t frame = 0; frame < frames; ++frame) {
        float gain = end_gain;
        if (target_gain < start_gain) {
            if (transition_frames == 1) {
                gain = target_gain;
            } else if (frame < transition_frames) {
                gain = start_gain + (target_gain - start_gain)
                    * static_cast<float>(frame)
                    / static_cast<float>(transition_frames - 1);
            }
        } else if (frames > 1) {
            gain = start_gain + (end_gain - start_gain)
                * static_cast<float>(frame)
                / static_cast<float>(frames - 1);
        }
        const std::size_t offset = static_cast<std::size_t>(frame) * 2;
        output[offset] = soft_limit(output[offset] * gain);
        output[offset + 1] = soft_limit(output[offset + 1] * gain);
    }
    mixer.master_gain = std::clamp(end_gain, 0.0F, 1.0F);
}

void restore_at(Mixer& mixer, std::int64_t target_frame) {
    mixer.frame = std::max<std::int64_t>(0, target_frame);
    mixer.event_index = static_cast<std::size_t>(std::lower_bound(
        mixer.events.begin(),
        mixer.events.end(),
        mixer.frame,
        [](const Event& event, std::int64_t frame) { return event.frame < frame; }
    ) - mixer.events.begin());
    mixer.voices.clear();
    for (std::size_t index = 0; index < mixer.event_index; ++index) {
        const Event& event = mixer.events[index];
        const std::int64_t age = mixer.frame - event.frame;
        if (age < event.audible_frames) {
            start_voice(mixer, event, age);
        }
    }
}

}  // namespace

BDO_AUDIO_API std::uint32_t bdo_audio_abi_version() {
    return kAbiVersion;
}

BDO_AUDIO_API std::uint64_t bdo_audio_capabilities() {
    return kCapabilityBasicStereoMix
        | kCapabilityExactFrameScheduling
        | kCapabilitySeek
        | kCapabilitySampleLoop
        | kCapabilityBoundedVoices
        | kCapabilityVoiceEnvelope
        | kCapabilityArticulationEnvelope
        | kCapabilityMasterLimiter;
}

BDO_AUDIO_API void* bdo_audio_create(
    std::int32_t sample_rate,
    std::int32_t max_voices
) {
    return new (std::nothrow) Mixer(sample_rate, max_voices);
}

BDO_AUDIO_API void bdo_audio_destroy(void* handle) {
    delete static_cast<Mixer*>(handle);
}

BDO_AUDIO_API std::int32_t bdo_audio_reset_plan(void* handle) {
    auto* mixer = static_cast<Mixer*>(handle);
    if (mixer == nullptr) {
        return -1;
    }
    mixer->samples.clear();
    mixer->events.clear();
    mixer->voices.clear();
    mixer->frame = 0;
    mixer->event_index = 0;
    mixer->voice_steals = 0;
    mixer->next_serial = 0;
    mixer->master_gain = 1.0F;
    mixer->finalised = false;
    return 0;
}

BDO_AUDIO_API std::int32_t bdo_audio_add_sample_f32_stereo(
    void* handle,
    const float* pcm,
    std::int64_t frames
) {
    auto* mixer = static_cast<Mixer*>(handle);
    if (mixer == nullptr || pcm == nullptr || frames <= 1) {
        return -1;
    }
    try {
        Sample sample;
        sample.frames = frames;
        sample.pcm.assign(pcm, pcm + frames * 2);
        mixer->samples.push_back(std::move(sample));
        mixer->finalised = false;
        return static_cast<std::int32_t>(mixer->samples.size() - 1);
    } catch (...) {
        return -2;
    }
}

BDO_AUDIO_API std::int32_t bdo_audio_add_event_v1(
    void* handle,
    std::int64_t frame,
    std::int32_t sample_index,
    double ratio,
    float gain,
    std::int64_t duration_frames,
    std::int64_t loop_start_frame,
    std::int64_t loop_end_frame
) {
    auto* mixer = static_cast<Mixer*>(handle);
    if (mixer == nullptr
        || sample_index < 0
        || static_cast<std::size_t>(sample_index) >= mixer->samples.size()
        || frame < 0
        || !std::isfinite(ratio)
        || ratio <= 0.0
        || !std::isfinite(gain)
        || duration_frames <= 0) {
        return -1;
    }
    try {
        mixer->events.push_back(Event{
            frame,
            sample_index,
            ratio,
            gain,
            duration_frames,
            loop_start_frame,
            loop_end_frame,
            duration_frames,
            0,
            0,
            0,
            0,
            false,
            mixer->next_serial++,
        });
        mixer->finalised = false;
        return 0;
    } catch (...) {
        return -2;
    }
}

BDO_AUDIO_API std::int32_t bdo_audio_add_event_v2(
    void* handle,
    std::int64_t frame,
    std::int32_t sample_index,
    double ratio,
    float gain,
    std::int64_t duration_frames,
    std::int64_t loop_start_frame,
    std::int64_t loop_end_frame,
    std::int64_t audible_frames,
    std::int64_t fade_in_frames,
    std::int64_t fade_out_frames
) {
    auto* mixer = static_cast<Mixer*>(handle);
    if (mixer == nullptr
        || sample_index < 0
        || static_cast<std::size_t>(sample_index) >= mixer->samples.size()
        || frame < 0
        || !std::isfinite(ratio)
        || ratio <= 0.0
        || !std::isfinite(gain)
        || duration_frames <= 0
        || audible_frames <= 0
        || fade_in_frames < 0
        || fade_out_frames < 0) {
        return -1;
    }
    try {
        mixer->events.push_back(Event{
            frame,
            sample_index,
            ratio,
            gain,
            duration_frames,
            loop_start_frame,
            loop_end_frame,
            audible_frames,
            std::min(fade_in_frames, audible_frames),
            std::min(fade_out_frames, audible_frames),
            0,
            0,
            false,
            mixer->next_serial++,
        });
        mixer->finalised = false;
        return 0;
    } catch (...) {
        return -2;
    }
}

BDO_AUDIO_API std::int32_t bdo_audio_add_event_v3(
    void* handle,
    std::int64_t frame,
    std::int32_t sample_index,
    double ratio,
    float gain,
    std::int64_t duration_frames,
    std::int64_t loop_start_frame,
    std::int64_t loop_end_frame,
    std::int64_t audible_frames,
    std::int64_t fade_in_frames,
    std::int64_t fade_out_frames,
    std::int32_t instrument_id,
    std::int32_t ntype,
    std::int32_t native_articulation
) {
    auto* mixer = static_cast<Mixer*>(handle);
    if (mixer == nullptr
        || sample_index < 0
        || static_cast<std::size_t>(sample_index) >= mixer->samples.size()
        || frame < 0
        || !std::isfinite(ratio)
        || ratio <= 0.0
        || !std::isfinite(gain)
        || duration_frames <= 0
        || audible_frames <= 0
        || fade_in_frames < 0
        || fade_out_frames < 0
        || ntype < 0
        || ntype > 255) {
        return -1;
    }
    try {
        mixer->events.push_back(Event{
            frame,
            sample_index,
            ratio,
            gain,
            duration_frames,
            loop_start_frame,
            loop_end_frame,
            audible_frames,
            std::min(fade_in_frames, audible_frames),
            std::min(fade_out_frames, audible_frames),
            instrument_id,
            ntype,
            native_articulation != 0,
            mixer->next_serial++,
        });
        mixer->finalised = false;
        return 0;
    } catch (...) {
        return -2;
    }
}

BDO_AUDIO_API std::int32_t bdo_audio_finalise_plan(void* handle) {
    auto* mixer = static_cast<Mixer*>(handle);
    if (mixer == nullptr) {
        return -1;
    }
    std::stable_sort(
        mixer->events.begin(),
        mixer->events.end(),
        [](const Event& left, const Event& right) {
            if (left.frame != right.frame) {
                return left.frame < right.frame;
            }
            return left.serial < right.serial;
        }
    );
    mixer->finalised = true;
    restore_at(*mixer, 0);
    return 0;
}

BDO_AUDIO_API std::int32_t bdo_audio_seek(void* handle, std::int64_t frame) {
    auto* mixer = static_cast<Mixer*>(handle);
    if (mixer == nullptr || !mixer->finalised || frame < 0) {
        return -1;
    }
    restore_at(*mixer, frame);
    return 0;
}

BDO_AUDIO_API std::int32_t bdo_audio_render_f32_stereo(
    void* handle,
    float* output,
    std::int32_t frames
) {
    auto* mixer = static_cast<Mixer*>(handle);
    if (mixer == nullptr || !mixer->finalised || output == nullptr || frames <= 0) {
        return -1;
    }
    std::memset(output, 0, static_cast<std::size_t>(frames) * 2 * sizeof(float));
    for (std::int32_t local_frame = 0; local_frame < frames; ++local_frame) {
        while (mixer->event_index < mixer->events.size()
               && mixer->events[mixer->event_index].frame <= mixer->frame) {
            const Event& event = mixer->events[mixer->event_index++];
            start_voice(*mixer, event, mixer->frame - event.frame);
        }

        float left = 0.0F;
        float right = 0.0F;
        std::size_t voice_index = 0;
        while (voice_index < mixer->voices.size()) {
            Voice& voice = mixer->voices[voice_index];
            const Sample& sample = mixer->samples[
                static_cast<std::size_t>(voice.sample_index)
            ];
            wrap_position(voice, sample);
            const auto first = static_cast<std::int64_t>(voice.position);
            if (voice.remaining_frames <= 0 || first < 0 || first >= sample.frames) {
                mixer->voices.erase(mixer->voices.begin() + static_cast<std::ptrdiff_t>(voice_index));
                continue;
            }
            std::int64_t second = first + 1;
            if (valid_loop(voice, sample) && second >= voice.loop_end_frame) {
                second = voice.loop_start_frame;
            } else if (second >= sample.frames) {
                second = sample.frames - 1;
            }
            const float fraction = static_cast<float>(
                voice.position - static_cast<double>(first)
            );
            float transition_gain = 1.0F;
            if (voice.fade_in_frames > 0
                && voice.age_frames < voice.fade_in_frames) {
                transition_gain *= std::clamp(
                    static_cast<float>(voice.age_frames + 1)
                        / static_cast<float>(voice.fade_in_frames),
                    0.0F,
                    1.0F
                );
            }
            const std::int64_t fade_start_age =
                voice.audible_frames - voice.fade_out_frames;
            if (voice.fade_out_frames > 0
                && voice.age_frames >= fade_start_age) {
                transition_gain *= std::clamp(
                    static_cast<float>(
                        voice.audible_frames - voice.age_frames - 1
                    ) / static_cast<float>(voice.fade_out_frames),
                    0.0F,
                    1.0F
                );
            }
            const std::size_t first_offset = static_cast<std::size_t>(first) * 2;
            const std::size_t second_offset = static_cast<std::size_t>(second) * 2;
            const float technique_gain = articulation_gain(
                voice,
                mixer->sample_rate
            );
            float voice_left = (sample.pcm[first_offset]
                + (sample.pcm[second_offset] - sample.pcm[first_offset]) * fraction)
                * voice.gain * technique_gain;
            float voice_right = (sample.pcm[first_offset + 1]
                + (sample.pcm[second_offset + 1] - sample.pcm[first_offset + 1]) * fraction)
                * voice.gain * technique_gain;
            if (!voice.native_articulation
                && (voice.ntype == 21 || voice.ntype == 22)) {
                voice_left = std::tanh(voice_left * 1.35F);
                voice_right = std::tanh(voice_right * 1.35F);
            }
            left += voice_left * transition_gain;
            right += voice_right * transition_gain;
            voice.position += voice.ratio;
            ++voice.age_frames;
            --voice.remaining_frames;
            ++voice_index;
        }
        output[static_cast<std::size_t>(local_frame) * 2] = left;
        output[static_cast<std::size_t>(local_frame) * 2 + 1] = right;
        ++mixer->frame;
    }
    apply_master_output(*mixer, output, frames);
    return frames;
}

BDO_AUDIO_API std::int64_t bdo_audio_position_frame(void* handle) {
    const auto* mixer = static_cast<const Mixer*>(handle);
    return mixer == nullptr ? -1 : mixer->frame;
}

BDO_AUDIO_API std::int32_t bdo_audio_active_voices(void* handle) {
    const auto* mixer = static_cast<const Mixer*>(handle);
    return mixer == nullptr
        ? -1
        : static_cast<std::int32_t>(mixer->voices.size());
}

BDO_AUDIO_API std::uint64_t bdo_audio_voice_steals(void* handle) {
    const auto* mixer = static_cast<const Mixer*>(handle);
    return mixer == nullptr ? 0 : mixer->voice_steals;
}
