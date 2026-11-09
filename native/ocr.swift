// Koç PDF Pro — metin tanıma yardımcısı (Apple Vision, internetsiz).
// Kullanım: kocpdf-ocr sayfa1.png [sayfa2.png …]
// Çıktı (JSON): her görüntü için satır listesi; konumlar 0–1 arası, sol üst köşe başlangıç.
//   [[{"text": "...", "x": 0.1, "y": 0.2, "w": 0.5, "h": 0.02, "conf": 0.98}, ...], ...]
import Foundation
import Vision

func recognize(_ path: String) -> [[String: Any]] {
    let url = URL(fileURLWithPath: path)
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    let supported = (try? request.supportedRecognitionLanguages()) ?? []
    let wanted = ["tr-TR", "en-US"].filter { supported.contains($0) }
    if !wanted.isEmpty { request.recognitionLanguages = wanted }
    let handler = VNImageRequestHandler(url: url, options: [:])
    do {
        try handler.perform([request])
    } catch {
        FileHandle.standardError.write("\(path): \(error.localizedDescription)\n".data(using: .utf8)!)
        return []
    }
    var lines: [[String: Any]] = []
    for observation in request.results ?? [] {
        guard let best = observation.topCandidates(1).first else { continue }
        let box = observation.boundingBox   // Vision: sol alt başlangıçlı, 0–1 arası
        lines.append([
            "text": best.string,
            "x": box.minX, "y": 1 - box.maxY, "w": box.width, "h": box.height,
            "conf": best.confidence,
        ])
    }
    return lines
}

let results = CommandLine.arguments.dropFirst().map(recognize)
let data = try JSONSerialization.data(withJSONObject: results)
FileHandle.standardOutput.write(data)
