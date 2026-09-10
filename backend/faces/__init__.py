"""Face detection, embedding, and bounded similarity subsystem.

Model: InsightFace buffalo_sc — RetinaFace detection + ArcFace 512-D embeddings.
Backend: ONNX Runtime (CPU; CoreML optional on Apple Silicon).

License note
-----------
InsightFace library code: MIT License.
Pre-trained model weights (buffalo_sc): non-commercial research use only.
Operators are responsible for applicable privacy law and platform terms.
This subsystem performs bounded face-similarity analysis against the
candidate set already discovered by the investigation. It does NOT crawl
the internet for arbitrary faces and does NOT constitute internet-wide
biometric identification.
"""
