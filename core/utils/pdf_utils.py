"""
PDF utilities for converting documents.

Reference: spec://utils/pdf_utils
"""

import os
import subprocess
import shutil
import logging
import tempfile

logger = logging.getLogger(__name__)


def convert_docx_to_pdf(docx_path: str, pdf_path: str) -> bool:
    """
    Converts a DOCX file to a PDF file using headless LibreOffice.

    Args:
        docx_path: Path to the input DOCX file.
        pdf_path: Path to save the output PDF file.

    Returns:
        True if the conversion succeeded, False otherwise.
    """
    if not os.path.exists(docx_path):
        logger.error(f"Input DOCX file does not exist: {docx_path}")
        return False

    try:
        # LibreOffice outputs to a directory, using the base name of the input file
        outdir = os.path.dirname(os.path.abspath(pdf_path))
        input_filename = os.path.basename(docx_path)
        base_name = os.path.splitext(input_filename)[0]
        expected_pdf_name = base_name + ".pdf"
        expected_pdf_path = os.path.join(outdir, expected_pdf_name)

        # Build command with isolated user profile to avoid lockups
        profile_dir = os.path.join(tempfile.gettempdir(), "libreoffice_pdf_export_profile")
        cmd = [
            "libreoffice",
            f"-env:UserInstallation=file://{profile_dir}",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            outdir,
            docx_path,
        ]

        logger.info(f"Running conversion command: {' '.join(cmd)}")

        # Run subprocess with a timeout of 30 seconds
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=True
        )

        logger.debug(f"LibreOffice stdout: {result.stdout.decode('utf-8', errors='ignore')}")
        logger.debug(f"LibreOffice stderr: {result.stderr.decode('utf-8', errors='ignore')}")

        if os.path.exists(expected_pdf_path):
            # If the expected PDF path is not where the user wants it, rename/move it
            if os.path.abspath(expected_pdf_path) != os.path.abspath(pdf_path):
                if os.path.exists(pdf_path):
                    os.remove(pdf_path)
                shutil.move(expected_pdf_path, pdf_path)
            logger.info(f"Successfully converted {docx_path} to {pdf_path}")
            return True
        else:
            logger.error(f"LibreOffice did not generate expected PDF at: {expected_pdf_path}")
            return False

    except subprocess.TimeoutExpired:
        logger.error("LibreOffice conversion timed out.")
        return False
    except subprocess.CalledProcessError as e:
        logger.error(f"LibreOffice command failed: {e.stderr.decode('utf-8', errors='ignore')}")
        return False
    except Exception as e:
        logger.error(f"Failed to convert DOCX to PDF: {e}")
        return False
