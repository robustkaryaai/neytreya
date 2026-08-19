import Foundation
import ScreenCaptureKit
import AVFoundation

// ---------------------------------------------------------------------------
// AudioCapture.swift — Neytreya system audio helper
// Captures speaker output using ScreenCaptureKit (no virtual driver needed)
// Writes 30-second WAV chunks to stdout as:
//   [4-byte little-endian UInt32 chunk_size][wav_bytes]
// ---------------------------------------------------------------------------

class AudioCapture: NSObject, SCStreamOutput, SCStreamDelegate {
    private var stream: SCStream?
    private var audioBuffer: [Float] = []
    private let sampleRate: Double = 16000  // 16kHz is optimal for Whisper
    private let channelCount: Int = 1       // mono is fine for speech
    private let chunkSeconds: Double = 30
    private var samplesPerChunk: Int { Int(sampleRate * chunkSeconds) }
    private let ioQueue = DispatchQueue(label: "neytreya.audiocap.io")
    private let semaphore = DispatchSemaphore(value: 0)

    func run() {
        Task {
            do {
                let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)
                guard let display = content.displays.first else {
                    fputs("AUDIOCAP_ERROR: no display found\n", stderr)
                    exit(1)
                }
                let filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])
                let cfg = SCStreamConfiguration()
                cfg.capturesAudio           = true
                cfg.sampleRate              = Int(sampleRate)
                cfg.channelCount            = channelCount
                cfg.excludesCurrentProcessAudio = true
                // Minimise video cost — we only need audio
                cfg.width  = 2
                cfg.height = 2
                cfg.minimumFrameInterval = CMTime(value: 1, timescale: 1)
                stream = SCStream(filter: filter, configuration: cfg, delegate: self)
                try stream?.addStreamOutput(self, type: .audio, sampleHandlerQueue: ioQueue)
                try await stream?.startCapture()
                fputs("AUDIOCAP_READY\n", stderr)
            } catch {
                fputs("AUDIOCAP_ERROR: \(error)\n", stderr)
                exit(1)
            }
        }
        RunLoop.main.run()
    }

    // MARK: SCStreamOutput
    func stream(_ stream: SCStream,
                didOutputSampleBuffer sb: CMSampleBuffer,
                of type: SCStreamOutputType) {
        guard type == .audio else { return }
        guard let block = sb.dataBuffer else { return }

        let len = CMBlockBufferGetDataLength(block)
        var raw = [UInt8](repeating: 0, count: len)
        CMBlockBufferCopyDataBytes(block, atOffset: 0, dataLength: len, destination: &raw)

        // Input is Float32 interleaved; convert to mono Float32 at target rate
        let floatCount = len / 4
        let floats = raw.withUnsafeBytes {
            Array($0.bindMemory(to: Float.self).prefix(floatCount))
        }
        audioBuffer.append(contentsOf: floats)

        if audioBuffer.count >= samplesPerChunk {
            let chunk = Array(audioBuffer.prefix(samplesPerChunk))
            audioBuffer.removeFirst(samplesPerChunk)
            writeChunk(chunk)
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        fputs("AUDIOCAP_STOPPED: \(error)\n", stderr)
        exit(0)
    }

    // MARK: WAV writer
    private func writeChunk(_ samples: [Float]) {
        let wav = buildWAV(samples)
        var size = UInt32(wav.count).littleEndian
        FileHandle.standardOutput.write(Data(bytes: &size, count: 4))
        FileHandle.standardOutput.write(wav)
    }

    private func buildWAV(_ samples: [Float]) -> Data {
        let ch      = UInt16(channelCount)
        let sr      = UInt32(sampleRate)
        let bps     = UInt16(32)
        let blk     = ch * (bps / 8)
        let byteRate = sr * UInt32(blk)
        let dataSize = UInt32(samples.count * 4)

        var d = Data()
        func u16(_ v: UInt16) { var x = v.littleEndian; d.append(contentsOf: withUnsafeBytes(of: x) { Array($0) }) }
        func u32(_ v: UInt32) { var x = v.littleEndian; d.append(contentsOf: withUnsafeBytes(of: x) { Array($0) }) }

        d.append(contentsOf: "RIFF".utf8); u32(36 + dataSize)
        d.append(contentsOf: "WAVE".utf8)
        d.append(contentsOf: "fmt ".utf8); u32(16)
        u16(3); u16(ch); u32(sr); u32(byteRate); u16(blk); u16(bps)
        d.append(contentsOf: "data".utf8); u32(dataSize)
        for s in samples { var f = s; d.append(contentsOf: withUnsafeBytes(of: f) { Array($0) }) }
        return d
    }
}

let cap = AudioCapture()
cap.run()
