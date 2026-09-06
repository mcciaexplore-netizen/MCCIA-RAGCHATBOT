from paddleocr import PaddleOCRVL

# Initialize once (reuse across images if processing multiple)
pipeline = PaddleOCRVL(pipeline_version="v1")

def run_paddleocr_vl(image_path):
    output = pipeline.predict(image_path)
    text_result = ""
    for res in output:
        text_result += res.markdown  # or check res for the exact text attribute
    return text_result