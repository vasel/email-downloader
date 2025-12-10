import os

VERSION_FILE = 'version.txt'
VERSION_INFO_FILE = 'file_version_info.txt'

def get_next_version():

    with open(VERSION_FILE, 'r') as f:
        version_str = f.read().strip()
        parts = list(map(int, version_str.split('.')))
        
        # Increment patch
        parts[2] += 1
        return parts

def write_version(parts):
    version_str = ".".join(map(str, parts))
    with open(VERSION_FILE, 'w') as f:
        f.write(version_str)
    return version_str, parts

def create_version_info_file(version_parts):
    # PyInstaller version file format
    # Windows version resource usually requires 4 numbers (Major, Minor, Patch, Build)
    # We will use 0 for Build
    v = version_parts + [0]
    version_tuple = tuple(v)
    version_str = ".".join(map(str, version_parts))
    
    content = f"""# UTF-8
#
# For more details about fixed file info 'ffi' see:
# http://msdn.microsoft.com/en-us/library/ms646997.aspx
VSVersionInfo(
  ffi=FixedFileInfo(
    # filevers and prodvers should be always a tuple with four items: (1, 2, 3, 4)
    # Set not needed items to zero 0.
    filevers={version_tuple},
    prodvers={version_tuple},
    # Contains a bitmask that specifies the valid bits 'flags'r
    mask=0x3f,
    # Contains a bitmask that specifies the Boolean attributes of the file.
    flags=0x0,
    # The operating system for which this file was designed.
    # 0x4 - NT and there is no need to define OS for Windows 95/98.
    OS=0x40004,
    # The general type of file.
    # 0x1 - the file is an application.
    fileType=0x1,
    # The function of the file.
    # 0x0 - the function is not defined for this fileType
    subtype=0x0,
    # Creation date and time stamp.
    date=(0, 0)
    ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        u'040904B0',
        [StringStruct(u'CompanyName', u'Email Downloader'),
        StringStruct(u'FileDescription', u'Email Downloader Tool'),
        StringStruct(u'FileVersion', u'{version_str}'),
        StringStruct(u'InternalName', u'email_downloader'),
        StringStruct(u'LegalCopyright', u'MIT License'),
        StringStruct(u'OriginalFilename', u'email_downloader.exe'),
        StringStruct(u'ProductName', u'Email Downloader'),
        StringStruct(u'ProductVersion', u'{version_str}')])
      ]), 
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"""
    with open(VERSION_INFO_FILE, 'w', encoding='utf-8') as f:
        f.write(content)

def main():
    parts = get_next_version()
    v_str, _ = write_version(parts)
    create_version_info_file(parts)
    print(f"Build Version Updated to: {v_str}")

if __name__ == '__main__':
    main()
