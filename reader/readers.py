import fitz  # this is pymupdf


def tokenize_pdf_statement(file_path):
    """
    :param file_path: path of pdf statement
    :return: list of items per each text field
    """
    with fitz.open(file_path) as doc:
        text = ""
        for page in doc:
            text += page.getText()

    return list(filter(None, text.split('\n')))
