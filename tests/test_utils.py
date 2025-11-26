import unittest
import os
import shutil
import tempfile
from utils import sanitize_filename, ensure_directory, calculate_sha1, create_zip_archive

class TestUtils(unittest.TestCase):

    def setUp(self):
        # Create a temporary directory for file operations
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        # Remove the temporary directory after tests
        shutil.rmtree(self.test_dir)

    def test_sanitize_filename(self):
        self.assertEqual(sanitize_filename("valid_name.txt"), "valid_name.txt")
        self.assertEqual(sanitize_filename("invalid/name.txt"), "invalid_name.txt")
        self.assertEqual(sanitize_filename("name with spaces"), "name_with_spaces")
        self.assertEqual(sanitize_filename("special@#chars"), "special__chars")
        self.assertEqual(sanitize_filename(".."), "..") # Depending on implementation, this might be allowed or not, but regex says keep dots

    def test_ensure_directory(self):
        new_dir = os.path.join(self.test_dir, "subdir")
        self.assertFalse(os.path.exists(new_dir))
        ensure_directory(new_dir)
        self.assertTrue(os.path.exists(new_dir))
        self.assertTrue(os.path.isdir(new_dir))
        # Ensure calling it again doesn't raise error
        ensure_directory(new_dir)

    def test_calculate_sha1(self):
        file_path = os.path.join(self.test_dir, "test_file.txt")
        content = b"test content"
        with open(file_path, "wb") as f:
            f.write(content)
        
        # SHA1 of "test content"
        # echo -n "test content" | sha1sum -> 1eebdf4fdc9fc7bf283031b93f9aef3338de9052
        expected_sha1 = "1eebdf4fdc9fc7bf283031b93f9aef3338de9052"
        self.assertEqual(calculate_sha1(file_path), expected_sha1)

    def test_create_zip_archive(self):
        src_dir = os.path.join(self.test_dir, "src")
        os.makedirs(src_dir)
        
        # Create a file in src
        with open(os.path.join(src_dir, "file1.txt"), "w") as f:
            f.write("content1")
            
        zip_path = os.path.join(self.test_dir, "archive.zip")
        create_zip_archive(src_dir, zip_path)
        
        self.assertTrue(os.path.exists(zip_path))
        
        # Verify zip content
        import zipfile
        with zipfile.ZipFile(zip_path, 'r') as zf:
            self.assertIn("file1.txt", zf.namelist())

if __name__ == '__main__':
    unittest.main()
