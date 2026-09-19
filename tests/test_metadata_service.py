import tempfile
from pathlib import Path

from app.services.metadata_service import MetadataService


def test_parse_nfo_not_found():
    """Test parsing non-existent NFO file returns None"""
    result = MetadataService.parse_nfo(Path("/nonexistent/file.nfo"))
    assert result is None


def test_parse_nfo_xml_content():
    """Test parsing valid NFO XML content"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".nfo", delete=False) as f:
        f.write("""<?xml version="1.0" encoding="utf-8"?>
<movie>
    <title>Test Movie</title>
    <originaltitle>Original Test Movie</originaltitle>
    <sorttitle>Test Movie, The</sorttitle>
    <alias>TM</alias>
    <year>2024</year>
    <plot>A test plot</plot>
    <rating>8.5</rating>
    <genre>Action</genre>
    <genre>Adventure</genre>
    <director>Test Director</director>
</movie>""")
        nfo_path = Path(f.name)

    try:
        result = MetadataService.parse_nfo(nfo_path)

        assert result is not None
        assert result["title"] == "Test Movie"
        assert result["original_title"] == "Original Test Movie"
        assert result["aliases"] == ["Test Movie, The", "TM"]
        assert result["year"] == "2024"
        assert result["plot"] == "A test plot"
        assert result["rating"] == "8.5"
        assert "Action" in result["genres"]
        assert "Adventure" in result["genres"]
        assert result["director"] == "Test Director"
    finally:
        nfo_path.unlink()


def test_parse_nfo_country_and_original_language():
    """Test parsing NFO country tags and inferring original language"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".nfo", delete=False) as f:
        f.write("""<?xml version="1.0" encoding="utf-8"?>
<movie>
    <title>Test Movie</title>
    <country>美国</country>
    <country>英国</country>
</movie>""")
        nfo_path = Path(f.name)

    try:
        result = MetadataService.parse_nfo(nfo_path)

        assert result is not None
        assert result["country"] == ["美国", "英国"]
        assert result["original_language"] == "英语"
    finally:
        nfo_path.unlink()


def test_parse_nfo_country_english_name():
    """Test inferring original language from English country names"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".nfo", delete=False) as f:
        f.write("""<?xml version="1.0" encoding="utf-8"?>
<tvshow>
    <title>Test Show</title>
    <country>Japan</country>
</tvshow>""")
        nfo_path = Path(f.name)

    try:
        result = MetadataService.parse_nfo(nfo_path)

        assert result is not None
        assert result["country"] == ["Japan"]
        assert result["original_language"] == "日语"
    finally:
        nfo_path.unlink()


def test_parse_nfo_country_unmapped():
    """Test NFO with unmapped country has no inferred original language"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".nfo", delete=False) as f:
        f.write("""<?xml version="1.0" encoding="utf-8"?>
<movie>
    <title>Test Movie</title>
    <country>Atlantis</country>
</movie>""")
        nfo_path = Path(f.name)

    try:
        result = MetadataService.parse_nfo(nfo_path)

        assert result is not None
        assert result["country"] == ["Atlantis"]
        assert "original_language" not in result
    finally:
        nfo_path.unlink()


def test_parse_nfo_gbk_encoding():
    """Test parsing NFO with GBK encoding"""
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".nfo", delete=False) as f:
        # Write GBK encoded content
        f.write(
            """<?xml version="1.0" encoding="utf-8"?>
<movie>
    <title>电影标题</title>
    <year>2023</year>
</movie>""".encode("gbk")
        )
        nfo_path = Path(f.name)

    try:
        result = MetadataService.parse_nfo(nfo_path)

        assert result is not None
        assert result["title"] == "电影标题"
        assert result["year"] == "2023"
    finally:
        nfo_path.unlink()


def test_find_poster_not_found():
    """Test finding poster in non-existent folder returns None"""
    result = MetadataService.find_poster(Path("/nonexistent"))
    assert result is None


def test_find_poster_standard_names():
    """Test finding poster with standard names"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Create poster file
        poster_path = tmp_path / "folder.jpg"
        poster_path.write_text("fake image")

        result = MetadataService.find_poster(tmp_path)

        assert result == poster_path


def test_find_poster_same_name():
    """Test finding poster with same name as video file"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Create video file
        video_path = tmp_path / "movie.mp4"
        video_path.write_text("fake video")

        # Create same-name poster
        poster_path = tmp_path / "movie.jpg"
        poster_path.write_text("fake image")

        result = MetadataService.find_poster(tmp_path, video_filename="movie.mp4")

        assert result == poster_path


def test_find_poster_priority_over_same_name():
    """Test that standard poster names take priority over same-name poster"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Create both standard and same-name poster
        (tmp_path / "folder.jpg").write_text("folder poster")
        (tmp_path / "movie.jpg").write_text("same name poster")

        result = MetadataService.find_poster(tmp_path, video_filename="movie.mp4")

        # Standard name should take priority
        assert result == tmp_path / "folder.jpg"


def test_parse_txt_info_not_found():
    """Test parsing non-existent TXT file returns None"""
    result = MetadataService.parse_txt_info(Path("/nonexistent/file.txt"))
    assert result is None


def test_parse_txt_info_valid():
    """Test parsing valid TXT metadata file"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("""title: Test Title
year: 2024
plot: A test description
another: value""")
        txt_path = Path(f.name)

    try:
        result = MetadataService.parse_txt_info(txt_path)

        assert result is not None
        assert result["title"] == "Test Title"
        assert result["year"] == "2024"
        assert result["plot"] == "A test description"
    finally:
        txt_path.unlink()


def test_find_nfo_file_not_found():
    """Test finding NFO file in non-existent folder returns None"""
    result = MetadataService.find_nfo_file(Path("/nonexistent"))
    assert result is None


def test_find_nfo_file_movie_nfo():
    """Test finding movie.nfo file"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Create movie.nfo
        nfo_path = tmp_path / "movie.nfo"
        nfo_path.write_text("test")

        result = MetadataService.find_nfo_file(tmp_path)

        assert result == nfo_path


def test_find_nfo_file_same_name():
    """Test finding NFO with same name as video"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Create video and same-name NFO
        (tmp_path / "video.mp4").write_text("test")
        nfo_path = tmp_path / "video.nfo"
        nfo_path.write_text("test")

        result = MetadataService.find_nfo_file(tmp_path, video_filename="video.mp4")

        assert result == nfo_path


def test_find_txt_file_not_found():
    """Test finding TXT file in non-existent folder returns None"""
    result = MetadataService.find_txt_file(Path("/nonexistent"))
    assert result is None


def test_find_txt_file_info_txt():
    """Test finding info.txt file"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Create info.txt
        txt_path = tmp_path / "info.txt"
        txt_path.write_text("test")

        result = MetadataService.find_txt_file(tmp_path)

        assert result == txt_path
