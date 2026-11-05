// 카메라 두 대 실시간 미리보기(macOS, 녹화·저장 없음). 한 창에 위/아래로 표시한다.
//
//   swift tools/camera_view_dual.swift                      # 위: 외부 카메라(USB 1-1.4, 180도 회전), 아래: SO-ARM 카메라(USB 1-1.1)
//   swift tools/camera_view_dual.swift --list               # 카메라 이름·uniqueID 목록
//   swift tools/camera_view_dual.swift --formats            # 카메라별 드라이버 보고 형식(FourCC·해상도·FPS)
//   swift tools/camera_view_dual.swift <위 uniqueID> <아래 uniqueID>
//   swift tools/camera_view_dual.swift --mirror <폴더>      # 카메라를 열지 않고 <폴더>/front.jpg·wrist.jpg를 보여 줌
//   swift tools/camera_view_dual.swift --mirror <폴더> --no-focus   # 창이 키보드 초점을 가져가지 않음(녹화 스페이스바용)
//                                                           # (rollout·record가 쓰는 중에 보는 방법, tools/rollout_with_view.sh)
//
// 같은 모델(Innomaker-U20CAM-720P) 두 대는 이름이 같아 번호·이름으로 구분할 수 없다.
// 그래서 AVFoundation uniqueID(USB 위치 기반, 예: 0x11100000c456367 = USB 위치 1-1.1)로 직접 연다.
// 카메라를 다른 USB 단자에 꽂으면 uniqueID가 바뀐다 → --list로 확인 후 인자로 넘긴다.
// 창을 닫거나 q/Esc를 누르면 종료한다.
//
// 주의: lerobot-rollout·record·teleop(카메라 포함)이 카메라를 쓰는 중에는 띄우지 않는다.
//   실측(2026-10-14): 공식 OpenCVCamera가 640×480으로 읽는 중에 이 창을 열면 장치 형식이 1280×720으로 바뀌어
//   그쪽 프레임이 640×360으로 들어오고, 크기 불일치로 읽기 스레드가 멈췄다(창을 닫아도 복구되지 않음).
//   preset을 640×480(vga640x480)으로 맞춰도 같았다. macOS에는 형식을 건드리지 않는 preset(inputPriority)이 없다.
import AppKit
import AVFoundation

let defaultTop = "0x11400000c456367"     // 외부 카메라(USB 위치 1-1.4)
let defaultBottom = "0x11100000c456367"  // SO-ARM에 달린 카메라(USB 위치 1-1.1)
let topRotation: CGFloat = 180            // 외부 카메라는 거꾸로 달려 있어 화면만 180도 회전(카메라 설정은 바꾸지 않음)
let bottomRotation: CGFloat = 0

func allVideoDevices() -> [AVCaptureDevice] {
    AVCaptureDevice.DiscoverySession(deviceTypes: [.builtInWideAngleCamera, .external],
                                     mediaType: .video, position: .unspecified).devices
}

func fourcc(_ v: FourCharCode) -> String {
    String([24, 16, 8, 0].map { Character(UnicodeScalar(UInt8((v >> $0) & 0xFF))) })
}

let args = Array(CommandLine.arguments.dropFirst())
if args.first == "--list" {
    for d in allVideoDevices() { print("\(d.localizedName.trimmingCharacters(in: .whitespaces)) | uniqueID=\(d.uniqueID)") }
    exit(0)
}
if args.first == "--formats" {
    // 드라이버(AVFoundation)가 보고하는 형식 목록. 캡처 세션을 열지 않는다.
    // 'dmb1' = Motion-JPEG(OpenDML), 'yuvs'/'2vuy' = YUY2/UYVY 4:2:2, '420v' = NV12 등.
    for d in allVideoDevices() {
        print("== \(d.localizedName.trimmingCharacters(in: .whitespaces)) | uniqueID=\(d.uniqueID) | model=\(d.modelID) | 제조사=\(d.manufacturer)")
        print("   현재 activeFormat: \(fourcc(CMFormatDescriptionGetMediaSubType(d.activeFormat.formatDescription))) "
              + "\(d.activeFormat.formatDescription.dimensions.width)x\(d.activeFormat.formatDescription.dimensions.height)")
        for f in d.formats {
            let dim = f.formatDescription.dimensions
            let rates = f.videoSupportedFrameRateRanges.map { r in
                r.minFrameRate == r.maxFrameRate ? String(format: "%.2f", r.maxFrameRate) : String(format: "%.2f-%.2f", r.minFrameRate, r.maxFrameRate)
            }.joined(separator: ",")
            print("   \(fourcc(CMFormatDescriptionGetMediaSubType(f.formatDescription))) \(dim.width)x\(dim.height) fps[\(rates)]")
        }
    }
    exit(0)
}
if args.first == "--snapshot" {
    // uniqueID로 카메라를 직접 열어 프레임 한 장씩 PNG로 저장(장치 매핑 확인용). 사용: --snapshot <저장 폴더> [uniqueID...]
    let outDir = URL(fileURLWithPath: args.count >= 2 ? args[1] : ".")
    try? FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)
    let ids = args.count >= 3 ? Array(args[2...]) : [defaultTop, defaultBottom]
    final class Grab: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate {
        var count = 0
        var image: CIImage?
        let done = DispatchSemaphore(value: 0)
        func captureOutput(_ o: AVCaptureOutput, didOutput sb: CMSampleBuffer, from c: AVCaptureConnection) {
            count += 1
            if count == 20, let pb = CMSampleBufferGetImageBuffer(sb) {  // 노출이 안정되도록 20번째 프레임 사용
                image = CIImage(cvPixelBuffer: pb)
                done.signal()
            }
        }
    }
    for id in ids {
        guard let dev = AVCaptureDevice(uniqueID: id), let input = try? AVCaptureDeviceInput(device: dev) else {
            print("열기 실패: \(id)"); continue
        }
        let session = AVCaptureSession()
        session.addInput(input)
        let out = AVCaptureVideoDataOutput()
        let g = Grab()
        out.setSampleBufferDelegate(g, queue: DispatchQueue(label: "grab"))
        session.addOutput(out)
        session.startRunning()
        _ = g.done.wait(timeout: .now() + 10)
        session.stopRunning()
        if let img = g.image {
            let url = outDir.appendingPathComponent("swift_\(id).png")
            try? CIContext().writePNGRepresentation(of: img, to: url, format: .RGBA8, colorSpace: CGColorSpaceCreateDeviceRGB())
            print("저장: \(url.path) \(Int(img.extent.width))x\(Int(img.extent.height)) (활성 형식 \(fourcc(CMFormatDescriptionGetMediaSubType(dev.activeFormat.formatDescription))))")
        } else {
            print("프레임 없음: \(id)")
        }
    }
    exit(0)
}
// --mirror: 카메라를 열지 않는다. 공식 프로세스가 내보낸 JPEG(scripts/so101_camera_mirror.py)를 0.1초마다 다시 읽어 보여 준다.
final class MirrorPane {
    let view: NSView
    let image = NSImageView()
    let label: NSTextField
    let path: String
    let title: String
    var lastMtime: Date?
    var shown = 0
    init(path: String, title: String, frame: NSRect) {
        self.path = path
        self.title = title
        view = NSView(frame: frame)
        view.wantsLayer = true
        view.layer?.backgroundColor = NSColor.black.cgColor
        image.frame = view.bounds
        image.imageScaling = .scaleProportionallyUpOrDown
        image.autoresizingMask = [.width, .height]
        view.addSubview(image)
        label = NSTextField(labelWithString: "\(title) — 영상 기다리는 중")
        label.textColor = .white
        label.backgroundColor = NSColor.black.withAlphaComponent(0.55)
        label.drawsBackground = true
        label.font = .boldSystemFont(ofSize: 13)
        label.frame = NSRect(x: 8, y: frame.height - 26, width: frame.width - 16, height: 20)
        label.autoresizingMask = [.width, .minYMargin]
        view.addSubview(label)
    }
    func refresh() {
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: path),
              let mtime = attrs[.modificationDate] as? Date else {
            label.stringValue = "\(title) — 영상 기다리는 중(\((path as NSString).lastPathComponent) 없음)"
            label.textColor = .white
            return
        }
        if mtime != lastMtime, let img = NSImage(contentsOfFile: path) {
            image.image = img
            lastMtime = mtime
            shown += 1
        }
        let age = Date().timeIntervalSince(mtime)
        if age > 1.0 {
            label.stringValue = "\(title) — 멈춤: 마지막 영상 \(String(format: "%.1f", age))초 전"
            label.textColor = .systemOrange
        } else {
            label.stringValue = "\(title) — 실시간(정책이 받는 영상)"
            label.textColor = .white
        }
    }
}

final class MirrorDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let dir: String
    var window: NSWindow!
    var panes: [MirrorPane] = []
    var tick = 0
    let focus: Bool
    init(dir: String, focus: Bool) { self.dir = dir; self.focus = focus }
    func applicationDidFinishLaunching(_ n: Notification) {
        let w: CGFloat = 640, h: CGFloat = 480
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: w / 1.5, height: h * 2 / 1.5),
                          styleMask: [.titled, .closable, .resizable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "실행 중 카메라 — 위: front / 아래: wrist (카메라를 열지 않음, q/Esc: 창만 닫기)"
        window.delegate = self
        let content = NSView(frame: NSRect(x: 0, y: 0, width: w, height: h * 2))
        let top = MirrorPane(path: dir + "/front.jpg", title: "위: front", frame: NSRect(x: 0, y: h, width: w, height: h))
        let bottom = MirrorPane(path: dir + "/wrist.jpg", title: "아래: wrist", frame: NSRect(x: 0, y: 0, width: w, height: h))
        top.view.autoresizingMask = [.width, .height, .minYMargin]
        bottom.view.autoresizingMask = [.width, .height, .maxYMargin]
        content.addSubview(top.view)
        content.addSubview(bottom.view)
        window.contentView = content
        window.setContentSize(NSSize(width: w / 1.5, height: h * 2 / 1.5))
        window.center()
        if focus {
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
        } else {
            window.orderFrontRegardless()  // 보이기만 하고 키보드 초점은 터미널에 남긴다(녹화 키 입력)
        }
        panes = [top, bottom]
        Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { _ in
            self.panes.forEach { $0.refresh() }
            self.tick += 1
            if self.tick % 50 == 0 { print("표시 갱신 누적: front \(top.shown), wrist \(bottom.shown)") }
        }
        NSEvent.addLocalMonitorForEvents(matching: .keyDown) { e in
            if e.keyCode == 53 || e.charactersIgnoringModifiers == "q" { NSApp.terminate(nil) }
            return e
        }
    }
    func windowWillClose(_ n: Notification) { NSApp.terminate(nil) }
    func applicationWillTerminate(_ n: Notification) {
        print("미러 보기 종료: front \(panes.first?.shown ?? 0)장, wrist \(panes.last?.shown ?? 0)장 표시")
    }
}

if args.first == "--mirror" {
    let dir = args.count >= 2 && args[1] != "--no-focus" ? args[1] : ".tmp/live"
    setvbuf(stdout, nil, _IOLBF, 0)
    let app = NSApplication.shared
    let focus = !args.contains("--no-focus")
    app.setActivationPolicy(focus ? .regular : .accessory)
    let md = MirrorDelegate(dir: dir, focus: focus)
    app.delegate = md
    print("미러 보기: \(dir)/front.jpg, wrist.jpg (카메라를 열지 않음)")
    app.run()
    exit(0)
}

let topID = args.count >= 2 ? args[0] : defaultTop
let bottomID = args.count >= 2 ? args[1] : defaultBottom

final class Pane {
    let session = AVCaptureSession()
    let view: NSView
    init(uniqueID: String, title: String, frame: NSRect, rotation: CGFloat = 0) {
        view = NSView(frame: frame)
        view.wantsLayer = true
        view.layer?.backgroundColor = NSColor.black.cgColor
        let label = NSTextField(labelWithString: title)
        label.textColor = .white
        label.backgroundColor = NSColor.black.withAlphaComponent(0.55)
        label.drawsBackground = true
        label.font = .boldSystemFont(ofSize: 13)
        label.frame = NSRect(x: 8, y: frame.height - 26, width: frame.width - 16, height: 20)
        label.autoresizingMask = [.width, .minYMargin]
        guard let dev = AVCaptureDevice(uniqueID: uniqueID) else {
            label.stringValue = "\(title) — 카메라 없음(uniqueID \(uniqueID)). --list로 확인"
            view.addSubview(label)
            FileHandle.standardError.write("카메라를 찾지 못함: \(uniqueID)\n".data(using: .utf8)!)
            return
        }
        do {
            let input = try AVCaptureDeviceInput(device: dev)
            session.beginConfiguration()
            if session.canSetSessionPreset(.hd1280x720) { session.sessionPreset = .hd1280x720 }
            if session.canAddInput(input) { session.addInput(input) }
            session.commitConfiguration()
        } catch {
            label.stringValue = "\(title) — 열기 실패: \(error.localizedDescription)"
        }
        let layer = AVCaptureVideoPreviewLayer(session: session)
        layer.videoGravity = .resizeAspect
        if rotation != 0 {
            if let c = layer.connection, c.isVideoRotationAngleSupported(rotation) {
                c.videoRotationAngle = rotation
            } else {
                FileHandle.standardError.write("화면 회전 \(rotation)도를 지원하지 않음: \(uniqueID)\n".data(using: .utf8)!)
            }
        }
        layer.frame = view.bounds
        layer.autoresizingMask = [.layerWidthSizable, .layerHeightSizable]
        view.layer?.addSublayer(layer)
        view.addSubview(label)
        print("\(title): \(dev.localizedName.trimmingCharacters(in: .whitespaces)) uniqueID=\(uniqueID) "
              + "형식 \(dev.activeFormat.formatDescription.dimensions.width)x\(dev.activeFormat.formatDescription.dimensions.height)"
              + (rotation != 0 ? ", 화면 \(Int(rotation))도 회전" : ""))
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    var window: NSWindow!
    var panes: [Pane] = []
    func applicationDidFinishLaunching(_ n: Notification) {
        let w: CGFloat = 640, h: CGFloat = 360
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: w, height: h * 2),
                          styleMask: [.titled, .closable, .resizable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "카메라 미리보기 — 위: 외부 / 아래: SO-ARM (q/Esc: 종료)"
        window.delegate = self
        let content = NSView(frame: NSRect(x: 0, y: 0, width: w, height: h * 2))
        // AppKit 좌표는 아래가 0 → 위 칸 y=h, 아래 칸 y=0
        let top = Pane(uniqueID: topID, title: "위: 외부 카메라 (\(topID))", frame: NSRect(x: 0, y: h, width: w, height: h), rotation: topRotation)
        let bottom = Pane(uniqueID: bottomID, title: "아래: SO-ARM 카메라 (\(bottomID))", frame: NSRect(x: 0, y: 0, width: w, height: h), rotation: bottomRotation)
        top.view.autoresizingMask = [.width, .height, .minYMargin]
        bottom.view.autoresizingMask = [.width, .height, .maxYMargin]
        content.addSubview(top.view)
        content.addSubview(bottom.view)
        window.contentView = content
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        panes = [top, bottom]
        DispatchQueue.global().async { self.panes.forEach { $0.session.startRunning() } }
        NSEvent.addLocalMonitorForEvents(matching: .keyDown) { e in
            if e.keyCode == 53 || e.charactersIgnoringModifiers == "q" { NSApp.terminate(nil) }
            return e
        }
    }
    func windowWillClose(_ n: Notification) { NSApp.terminate(nil) }
    func applicationWillTerminate(_ n: Notification) {
        panes.forEach { $0.session.stopRunning() }
        print("미리보기 종료")
    }
}

setvbuf(stdout, nil, _IOLBF, 0)
let app = NSApplication.shared
app.setActivationPolicy(.regular)
let delegate = AppDelegate()
app.delegate = delegate
app.run()
