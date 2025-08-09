from buttercup.program_model.api.fuzzy_imports_resolver import FuzzyCImportsResolver
import pytest
from buttercup.common.challenge_task import ChallengeTask


@pytest.mark.parametrize(
    "file_path,expected_imports", [("src/md5/md5.c", {"src/md5/md5.h"})]
)
@pytest.mark.integration
def test_list_direct_imports(
    libjpeg_main_oss_fuzz_task: ChallengeTask, file_path, expected_imports
):
    # Unit test for the get_direct_imports() function
    # We just check whether we can get imports in a single file properly
    resolver = FuzzyCImportsResolver(
        libjpeg_main_oss_fuzz_task.task_dir / "src/libjpeg-turbo"
    )
    path_prefix = libjpeg_main_oss_fuzz_task.task_dir / "src/libjpeg-turbo"
    full_path = (path_prefix / file_path).resolve()
    direct_imports = resolver.get_direct_imports(full_path)
    # Check resolved imports. We make found imports relative to
    # the task dir because the imports resolver returns full paths
    assert (
        set(map(lambda x: str(x.relative_to(path_prefix)), direct_imports))
        == expected_imports
    )


@pytest.mark.parametrize(
    "file_path,expected_imports",
    [
        ("src/md5/md5.c", {"src/md5/md5.h"}),
        (
            "src/jcicc.c",
            {
                "src/jinclude.h",
                "src/jpeglib.h",
                "src/jerror.h",
                "src/jmorecfg.h",
                "src/jpegint.h",
                "src/jconfig.h.in",
                "src/jconfigint.h.in",
            },
        ),
        (
            "src/jcapistd.c",
            {
                "src/jinclude.h",
                "src/jpeglib.h",
                "src/jsamplecomp.h",
                "src/jerror.h",
                "src/jmorecfg.h",
                "src/jpegint.h",
                "src/jconfig.h.in",
                "src/jconfigint.h.in",
            },
        ),
        (
            "simd/x86_64/jsimd.c",
            {
                "src/jdct.h",
                "src/jsimddct.h",
                "src/jinclude.h",
                "src/jsimd.h",
                "simd/jsimd.h",
                "src/jconfigint.h.in",
                "src/jconfig.h.in",
                "src/jmorecfg.h",
                "src/jpegint.h",
                "src/jerror.h",
                "src/jchuff.h",
                "src/jsamplecomp.h",
                "src/jpeglib.h",
            },
        ),
    ],
)
@pytest.mark.integration
def test_import_checker(
    libjpeg_main_oss_fuzz_task: ChallengeTask, file_path, expected_imports
):
    # Create resolver
    resolver = FuzzyCImportsResolver(
        libjpeg_main_oss_fuzz_task.task_dir / "src/libjpeg-turbo"
    )
    # Check expected imports
    for expected in expected_imports:
        assert resolver.is_file_imported_by(expected, file_path)
    # Check that file 'imports' itself (expected behaviour from the api)
    assert resolver.is_file_imported_by(file_path, file_path)
    # Check that we didn't get more imports than expected
    # We add +1 to include file_path itself in the imports
    assert len(resolver.get_all_imports(file_path)) == len(expected_imports) + 1
