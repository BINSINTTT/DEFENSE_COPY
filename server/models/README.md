# Leaf segmentation models

The encoder and decoder ONNX files were exported from the MobileSAM `vit_t`
checkpoint (`mobile_sam.pt`) in the project's local annotation workspace. The
source project is [MobileSAM](https://github.com/ChaoningZhang/MobileSAM).
Its Apache 2.0 license is included as `MobileSAM_LICENSE`.

The web server runs these files with ONNX Runtime on CPU. PyTorch is used only
to export them and is not a production dependency. The model selects a leaf
mask before disease detection; OpenCV is used afterward for severity.
