const RATE = 24000;
export const MAX_SECONDS = 60;

export async function recordingFile(blob, truncate = true) {
  const context = new OfflineAudioContext(1, 1, RATE);
  const audio = await context.decodeAudioData(await blob.arrayBuffer());
  if (audio.duration < 3) throw new Error("3초 이상 녹음해 주세요.");
  if (!truncate && audio.duration > MAX_SECONDS)
    throw new Error("음성 파일은 1분 이하로 준비해 주세요.");
  const length = Math.min(audio.length, RATE * MAX_SECONDS);
  const buffer = new ArrayBuffer(44 + length * 2);
  const view = new DataView(buffer);
  function text(offset, value) {
    for (let i = 0; i < value.length; i++)
      view.setUint8(offset + i, value.charCodeAt(i));
  }
  text(0, "RIFF");
  view.setUint32(4, 36 + length * 2, true);
  text(8, "WAVEfmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, RATE, true);
  view.setUint32(28, RATE * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, length * 2, true);
  const channels = Array.from({ length: audio.numberOfChannels }, (_, i) =>
    audio.getChannelData(i),
  );
  for (let i = 0; i < length; i++) {
    const sample = Math.max(
      -1,
      Math.min(
        1,
        channels.reduce((sum, channel) => sum + channel[i], 0) /
          channels.length,
      ),
    );
    view.setInt16(44 + i * 2, sample * (sample < 0 ? 32768 : 32767), true);
  }
  return new File([buffer], "마이크 녹음.wav", { type: "audio/wav" });
}
