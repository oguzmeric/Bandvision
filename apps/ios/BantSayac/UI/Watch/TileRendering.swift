import AVFoundation
import CoreMedia
import SwiftUI
import UIKit

/// Çözülmüş kareyi hemen gösterilecek örneğe sarar (piksel kopyası yok).
enum SampleBuffers {
    static func make(_ frame: CVPixelBuffer) -> CMSampleBuffer? {
        var format: CMVideoFormatDescription?
        guard CMVideoFormatDescriptionCreateForImageBuffer(allocator: kCFAllocatorDefault, imageBuffer: frame,
                                                           formatDescriptionOut: &format) == noErr,
              let format else { return nil }
        var timing = CMSampleTimingInfo(duration: .invalid,
                                        presentationTimeStamp: CMClockGetTime(CMClockGetHostTimeClock()),
                                        decodeTimeStamp: .invalid)
        var sample: CMSampleBuffer?
        guard CMSampleBufferCreateReadyWithImageBuffer(allocator: kCFAllocatorDefault, imageBuffer: frame,
                                                       formatDescription: format, sampleTiming: &timing,
                                                       sampleBufferOut: &sample) == noErr,
              let sample else { return nil }
        if let attachments = CMSampleBufferGetSampleAttachmentsArray(sample, createIfNecessary: true),
           CFArrayGetCount(attachments) > 0 {
            let dict = unsafeBitCast(CFArrayGetValueAtIndex(attachments, 0), to: CFMutableDictionary.self)
            CFDictionarySetValue(dict, Unmanaged.passUnretained(kCMSampleAttachmentKey_DisplayImmediately).toOpaque(),
                                 Unmanaged.passUnretained(kCFBooleanTrue).toOpaque())
        }
        return sample
    }
}

/// Hub'dan gelen kareyi kutunun görüntü katmanına verir ve kare sayar. Kareler çözücü iş parçacığından gelir;
/// katmana kendi sırasında verilir. Son kare saklanır: katman yeniden kurulunca (döndürme) hemen görünür.
final class TileSink: HubSubscriber, @unchecked Sendable {
    private let lock = NSLock()
    private var layer: AVSampleBufferDisplayLayer?
    private var last: CVPixelBuffer?
    private var frameCount = 0
    private var statusHandler: (@Sendable (TileStatus) -> Void)?
    private let queue = DispatchQueue(label: "bantsayac.tile")

    func setStatusHandler(_ handler: @escaping @Sendable (TileStatus) -> Void) {
        lock.lock(); statusHandler = handler; lock.unlock()
    }

    func attach(_ layer: AVSampleBufferDisplayLayer) {
        lock.lock()
        self.layer = layer
        let frame = last
        lock.unlock()
        if let frame { show(frame, on: layer) }
    }

    func detach(_ layer: AVSampleBufferDisplayLayer) {
        lock.lock()
        if self.layer === layer { self.layer = nil }
        lock.unlock()
    }

    /// Son çağrıdan beri gelen kare sayısı
    func takeFrameCount() -> Int {
        lock.lock(); defer { lock.unlock() }
        let n = frameCount
        frameCount = 0
        return n
    }

    func hubFrame(_ frame: CVPixelBuffer) {
        lock.lock()
        frameCount += 1
        last = frame
        let target = layer
        lock.unlock()
        if let target { show(frame, on: target) }
    }

    func hubStatus(_ status: TileStatus) {
        lock.lock()
        let handler = statusHandler
        lock.unlock()
        handler?(status)
    }

    private func show(_ frame: CVPixelBuffer, on layer: AVSampleBufferDisplayLayer) {
        guard let sample = SampleBuffers.make(frame) else { return }
        let job = UncheckedSendable(value: (layer, sample))
        queue.async {
            let (layer, sample) = job.value
            let renderer = layer.sampleBufferRenderer
            if renderer.status == .failed { renderer.flush() }
            guard renderer.isReadyForMoreMediaData else { return }   // geride kaldıysa kare atlanır
            renderer.enqueue(sample)
        }
    }
}

/// Kutunun görüntüsü: AVSampleBufferDisplayLayer (en-boy oranı korunur, arka plan siyah)
struct TileVideoView: UIViewRepresentable {
    let sink: TileSink

    final class LayerView: UIView {
        override class var layerClass: AnyClass { AVSampleBufferDisplayLayer.self }
        // layerClass yukarıda: katman her zaman bu türdedir
        var displayLayer: AVSampleBufferDisplayLayer { layer as! AVSampleBufferDisplayLayer }
    }

    final class Coordinator {
        var sink: TileSink?
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> LayerView {
        let view = LayerView()
        view.backgroundColor = .black
        view.displayLayer.videoGravity = .resizeAspect
        context.coordinator.sink = sink
        sink.attach(view.displayLayer)
        return view
    }

    func updateUIView(_ view: LayerView, context: Context) {
        guard context.coordinator.sink !== sink else { return }
        context.coordinator.sink?.detach(view.displayLayer)
        context.coordinator.sink = sink
        sink.attach(view.displayLayer)
    }

    static func dismantleUIView(_ view: LayerView, coordinator: Coordinator) {
        coordinator.sink?.detach(view.displayLayer)
    }
}
