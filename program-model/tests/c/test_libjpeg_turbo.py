"""CodeQuery primitives testing"""

import pytest

from buttercup.common.challenge_task import ChallengeTask
from buttercup.program_model.codequery import CodeQuery
from ..common import (
    common_test_get_type_definitions,
    common_test_get_callees,
    common_test_get_functions,
    common_test_get_callers,
    TestFunctionInfo,
    TestCallerInfo,
    TestCalleeInfo,
    TestTypeDefinitionInfo,
)
from buttercup.program_model.utils.common import TypeDefinitionType


# Test searching for functions in codebase where we expect
# only 1 function to be returned. To support multiple matches
# we should make `function_info` a list of expected function results
# instead of one result only
@pytest.mark.parametrize(
    "function_name,file_path,function_info",
    [
        (
            "process_data_context_main",
            "/src/libjpeg-turbo/jdmainct.c",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """process_data_context_main(j_decompress_ptr cinfo, JSAMPARRAY output_buf,
                          JDIMENSION *out_row_ctr, JDIMENSION out_rows_avail)
{
  my_main_ptr main_ptr = (my_main_ptr)cinfo->main;

  /* Read input data if we haven't filled the main buffer yet */
  if (!main_ptr->buffer_full) {""",
                    """/* Still need to process last row group of this iMCU row, */
    /* which is saved at index M+1 of the other xbuffer */
    main_ptr->rowgroup_ctr = (JDIMENSION)(cinfo->_min_DCT_scaled_size + 1);
    main_ptr->rowgroups_avail = (JDIMENSION)(cinfo->_min_DCT_scaled_size + 2);
    main_ptr->context_state = CTX_POSTPONED_ROW;
  }
}""",
                ],
            ),
        ),
        (
            "decompress_smooth_data",
            "/src/libjpeg-turbo/jdcoefct.c",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """decompress_smooth_data(j_decompress_ptr cinfo, JSAMPIMAGE output_buf)
{
  my_coef_ptr coef = (my_coef_ptr)cinfo->coef;
  JDIMENSION last_iMCU_row = cinfo->total_iMCU_rows - 1;
  JDIMENSION block_num, last_block_column;
  int ci, block_row, block_rows, access_rows;""",
                    """if (++(cinfo->output_iMCU_row) < cinfo->total_iMCU_rows)
    return JPEG_ROW_COMPLETED;
  return JPEG_SCAN_COMPLETED;""",
                ],
            ),
        ),
        (
            "jpeg_read_scanlines",
            "/src/libjpeg-turbo/jdapistd.c",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """jpeg_read_scanlines(j_decompress_ptr cinfo, JSAMPARRAY scanlines,
                    JDIMENSION max_lines)
{
  JDIMENSION row_ctr;

  if (cinfo->global_state != DSTATE_SCANNING)""",
                    """/* Process some data */
  row_ctr = 0;
  (*cinfo->main->process_data) (cinfo, scanlines, &row_ctr, max_lines);
  cinfo->output_scanline += row_ctr;
  return row_ctr;
}""",
                ],
            ),
        ),
    ],
)
@pytest.mark.integration
def test_libjpeg_get_functions(
    libjpeg_oss_fuzz_task: ChallengeTask,
    libjpeg_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    function_info,
):
    """Test that we can get functions in challenge task code"""
    common_test_get_functions(
        libjpeg_oss_fuzz_cq, function_name, file_path, function_info
    )


@pytest.mark.parametrize(
    "function_name,file_path,line_number,fuzzy,expected_callers,num_callers",
    [
        (
            "jpeg_read_scanlines",
            "/src/libjpeg-turbo/jdapistd.c",
            None,
            False,
            [
                TestCallerInfo(
                    name="tjDecompress2",
                    file_path="/src/libjpeg-turbo/turbojpeg.c",
                    start_line=1241,
                ),
                TestCallerInfo(
                    name="read_and_discard_scanlines",
                    file_path="/src/libjpeg-turbo/jdapistd.c",
                    start_line=317,
                ),
                TestCallerInfo(
                    name="main",
                    file_path="/src/libjpeg-turbo/djpeg.c",
                    start_line=533,
                ),
            ],
            3,
        ),
    ],
)
@pytest.mark.integration
def test_libjpeg_get_callers(
    libjpeg_oss_fuzz_task: ChallengeTask,
    libjpeg_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callers,
    num_callers,
):
    """Test that we can get function callers"""
    common_test_get_callers(
        libjpeg_oss_fuzz_task,
        libjpeg_oss_fuzz_cq,
        function_name,
        file_path,
        line_number,
        fuzzy,
        expected_callers,
        num_callers,
    )


@pytest.mark.parametrize(
    "function_name,file_path,line_number,fuzzy,expected_callees,num_callees",
    [
        (
            "jpeg_skip_scanlines",
            "/src/libjpeg-turbo/jdapistd.c",
            None,
            False,
            [
                TestCalleeInfo(
                    name="read_and_discard_scanlines",
                    file_path="/src/libjpeg-turbo/jdapistd.c",
                    start_line=318,
                ),
                TestCalleeInfo(
                    name="set_wraparound_pointers",
                    file_path="/src/libjpeg-turbo/jdmainct.h",
                    start_line=47,
                ),
                TestCalleeInfo(
                    name="increment_simple_rowgroup_ctr",
                    file_path="/src/libjpeg-turbo/jdapistd.c",
                    start_line=367,
                ),
                TestCalleeInfo(
                    name="start_iMCU_row",
                    file_path="/src/libjpeg-turbo/jdcoefct.h",
                    start_line=63,
                ),
            ],
            4,
        ),
    ],
)
@pytest.mark.integration
def test_get_callees(
    libjpeg_oss_fuzz_task: ChallengeTask,
    libjpeg_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callees,
    num_callees,
):
    """Test that we can get function callees."""
    common_test_get_callees(
        libjpeg_oss_fuzz_task,
        libjpeg_oss_fuzz_cq,
        function_name,
        file_path,
        line_number,
        fuzzy,
        expected_callees,
        num_callees,
    )


@pytest.mark.parametrize(
    "type_name,file_path,fuzzy,type_definition_info",
    [
        (
            "jpeg_decompress_struct",
            None,
            False,
            TestTypeDefinitionInfo(
                name="jpeg_decompress_struct",
                type=TypeDefinitionType.STRUCT,
                definition='/* Master record for a decompression instance */\n\nstruct jpeg_decompress_struct {\n  jpeg_common_fields;           /* Fields shared with jpeg_compress_struct */\n\n  /* Source of compressed data */\n  struct jpeg_source_mgr *src;\n\n  /* Basic description of image --- filled in by jpeg_read_header(). */\n  /* Application may inspect these values to decide how to process image. */\n\n  JDIMENSION image_width;       /* nominal image width (from SOF marker) */\n  JDIMENSION image_height;      /* nominal image height */\n  int num_components;           /* # of color components in JPEG image */\n  J_COLOR_SPACE jpeg_color_space; /* colorspace of JPEG image */\n\n  /* Decompression processing parameters --- these fields must be set before\n   * calling jpeg_start_decompress().  Note that jpeg_read_header() initializes\n   * them to default values.\n   */\n\n  J_COLOR_SPACE out_color_space; /* colorspace for output */\n\n  unsigned int scale_num, scale_denom; /* fraction by which to scale image */\n\n  double output_gamma;          /* image gamma wanted in output */\n\n  boolean buffered_image;       /* TRUE=multiple output passes */\n  boolean raw_data_out;         /* TRUE=downsampled data wanted */\n\n  J_DCT_METHOD dct_method;      /* IDCT algorithm selector */\n  boolean do_fancy_upsampling;  /* TRUE=apply fancy upsampling */\n  boolean do_block_smoothing;   /* TRUE=apply interblock smoothing */\n\n  boolean quantize_colors;      /* TRUE=colormapped output wanted */\n  /* the following are ignored if not quantize_colors: */\n  J_DITHER_MODE dither_mode;    /* type of color dithering to use */\n  boolean two_pass_quantize;    /* TRUE=use two-pass color quantization */\n  int desired_number_of_colors; /* max # colors to use in created colormap */\n  /* these are significant only in buffered-image mode: */\n  boolean enable_1pass_quant;   /* enable future use of 1-pass quantizer */\n  boolean enable_external_quant;/* enable future use of external colormap */\n  boolean enable_2pass_quant;   /* enable future use of 2-pass quantizer */\n\n  /* Description of actual output image that will be returned to application.\n   * These fields are computed by jpeg_start_decompress().\n   * You can also use jpeg_calc_output_dimensions() to determine these values\n   * in advance of calling jpeg_start_decompress().\n   */\n\n  JDIMENSION output_width;      /* scaled image width */\n  JDIMENSION output_height;     /* scaled image height */\n  int out_color_components;     /* # of color components in out_color_space */\n  int output_components;        /* # of color components returned */\n  /* output_components is 1 (a colormap index) when quantizing colors;\n   * otherwise it equals out_color_components.\n   */\n  int rec_outbuf_height;        /* min recommended height of scanline buffer */\n  /* If the buffer passed to jpeg_read_scanlines() is less than this many rows\n   * high, space and time will be wasted due to unnecessary data copying.\n   * Usually rec_outbuf_height will be 1 or 2, at most 4.\n   */\n\n  /* When quantizing colors, the output colormap is described by these fields.\n   * The application can supply a colormap by setting colormap non-NULL before\n   * calling jpeg_start_decompress; otherwise a colormap is created during\n   * jpeg_start_decompress or jpeg_start_output.\n   * The map has out_color_components rows and actual_number_of_colors columns.\n   */\n  int actual_number_of_colors;  /* number of entries in use */\n  JSAMPARRAY colormap;          /* The color map as a 2-D pixel array */\n\n  /* State variables: these variables indicate the progress of decompression.\n   * The application may examine these but must not modify them.\n   */\n\n  /* Row index of next scanline to be read from jpeg_read_scanlines().\n   * Application may use this to control its processing loop, e.g.,\n   * "while (output_scanline < output_height)".\n   */\n  JDIMENSION output_scanline;   /* 0 .. output_height-1  */\n\n  /* Current input scan number and number of iMCU rows completed in scan.\n   * These indicate the progress of the decompressor input side.\n   */\n  int input_scan_number;        /* Number of SOS markers seen so far */\n  JDIMENSION input_iMCU_row;    /* Number of iMCU rows completed */\n\n  /* The "output scan number" is the notional scan being displayed by the\n   * output side.  The decompressor will not allow output scan/row number\n   * to get ahead of input scan/row, but it can fall arbitrarily far behind.\n   */\n  int output_scan_number;       /* Nominal scan number being displayed */\n  JDIMENSION output_iMCU_row;   /* Number of iMCU rows read */\n\n  /* Current progression status.  coef_bits[c][i] indicates the precision\n   * with which component c\'s DCT coefficient i (in zigzag order) is known.\n   * It is -1 when no data has yet been received, otherwise it is the point\n   * transform (shift) value for the most recent scan of the coefficient\n   * (thus, 0 at completion of the progression).\n   * This pointer is NULL when reading a non-progressive file.\n   */\n  int (*coef_bits)[DCTSIZE2];   /* -1 or current Al value for each coef */\n\n  /* Internal JPEG parameters --- the application usually need not look at\n   * these fields.  Note that the decompressor output side may not use\n   * any parameters that can change between scans.\n   */\n\n  /* Quantization and Huffman tables are carried forward across input\n   * datastreams when processing abbreviated JPEG datastreams.\n   */\n\n  JQUANT_TBL *quant_tbl_ptrs[NUM_QUANT_TBLS];\n  /* ptrs to coefficient quantization tables, or NULL if not defined */\n\n  JHUFF_TBL *dc_huff_tbl_ptrs[NUM_HUFF_TBLS];\n  JHUFF_TBL *ac_huff_tbl_ptrs[NUM_HUFF_TBLS];\n  /* ptrs to Huffman coding tables, or NULL if not defined */\n\n  /* These parameters are never carried across datastreams, since they\n   * are given in SOF/SOS markers or defined to be reset by SOI.\n   */\n\n  int data_precision;           /* bits of precision in image data */\n\n  jpeg_component_info *comp_info;\n  /* comp_info[i] describes component that appears i\'th in SOF */\n\n#if JPEG_LIB_VERSION >= 80\n  boolean is_baseline;          /* TRUE if Baseline SOF0 encountered */\n#endif\n  boolean progressive_mode;     /* TRUE if SOFn specifies progressive mode */\n  boolean arith_code;           /* TRUE=arithmetic coding, FALSE=Huffman */\n\n  UINT8 arith_dc_L[NUM_ARITH_TBLS]; /* L values for DC arith-coding tables */\n  UINT8 arith_dc_U[NUM_ARITH_TBLS]; /* U values for DC arith-coding tables */\n  UINT8 arith_ac_K[NUM_ARITH_TBLS]; /* Kx values for AC arith-coding tables */\n\n  unsigned int restart_interval; /* MCUs per restart interval, or 0 for no restart */\n\n  /* These fields record data obtained from optional markers recognized by\n   * the JPEG library.\n   */\n  boolean saw_JFIF_marker;      /* TRUE iff a JFIF APP0 marker was found */\n  /* Data copied from JFIF marker; only valid if saw_JFIF_marker is TRUE: */\n  UINT8 JFIF_major_version;     /* JFIF version number */\n  UINT8 JFIF_minor_version;\n  UINT8 density_unit;           /* JFIF code for pixel size units */\n  UINT16 X_density;             /* Horizontal pixel density */\n  UINT16 Y_density;             /* Vertical pixel density */\n  boolean saw_Adobe_marker;     /* TRUE iff an Adobe APP14 marker was found */\n  UINT8 Adobe_transform;        /* Color transform code from Adobe marker */\n\n  boolean CCIR601_sampling;     /* TRUE=first samples are cosited */\n\n  /* Aside from the specific data retained from APPn markers known to the\n   * library, the uninterpreted contents of any or all APPn and COM markers\n   * can be saved in a list for examination by the application.\n   */\n  jpeg_saved_marker_ptr marker_list; /* Head of list of saved markers */\n\n  /* Remaining fields are known throughout decompressor, but generally\n   * should not be touched by a surrounding application.\n   */\n\n  /*\n   * These fields are computed during decompression startup\n   */\n  int max_h_samp_factor;        /* largest h_samp_factor */\n  int max_v_samp_factor;        /* largest v_samp_factor */\n\n#if JPEG_LIB_VERSION >= 70\n  int min_DCT_h_scaled_size;    /* smallest DCT_h_scaled_size of any component */\n  int min_DCT_v_scaled_size;    /* smallest DCT_v_scaled_size of any component */\n#else\n  int min_DCT_scaled_size;      /* smallest DCT_scaled_size of any component */\n#endif\n\n  JDIMENSION total_iMCU_rows;   /* # of iMCU rows in image */\n  /* The coefficient controller\'s input and output progress is measured in\n   * units of "iMCU" (interleaved MCU) rows.  These are the same as MCU rows\n   * in fully interleaved JPEG scans, but are used whether the scan is\n   * interleaved or not.  We define an iMCU row as v_samp_factor DCT block\n   * rows of each component.  Therefore, the IDCT output contains\n   * v_samp_factor*DCT_[v_]scaled_size sample rows of a component per iMCU row.\n   */\n\n  JSAMPLE *sample_range_limit;  /* table for fast range-limiting */\n\n  /*\n   * These fields are valid during any one scan.\n   * They describe the components and MCUs actually appearing in the scan.\n   * Note that the decompressor output side must not use these fields.\n   */\n  int comps_in_scan;            /* # of JPEG components in this scan */\n  jpeg_component_info *cur_comp_info[MAX_COMPS_IN_SCAN];\n  /* *cur_comp_info[i] describes component that appears i\'th in SOS */\n\n  JDIMENSION MCUs_per_row;      /* # of MCUs across the image */\n  JDIMENSION MCU_rows_in_scan;  /* # of MCU rows in the image */\n\n  int blocks_in_MCU;            /* # of DCT blocks per MCU */\n  int MCU_membership[D_MAX_BLOCKS_IN_MCU];\n  /* MCU_membership[i] is index in cur_comp_info of component owning */\n  /* i\'th block in an MCU */\n\n  int Ss, Se, Ah, Al;           /* progressive JPEG parameters for scan */\n\n#if JPEG_LIB_VERSION >= 80\n  /* These fields are derived from Se of first SOS marker.\n   */\n  int block_size;               /* the basic DCT block size: 1..16 */\n  const int *natural_order; /* natural-order position array for entropy decode */\n  int lim_Se;                   /* min( Se, DCTSIZE2-1 ) for entropy decode */\n#endif\n\n  /* This field is shared between entropy decoder and marker parser.\n   * It is either zero or the code of a JPEG marker that has been\n   * read from the data source, but has not yet been processed.\n   */\n  int unread_marker;\n\n  /*\n   * Links to decompression subobjects (methods, private variables of modules)\n   */\n  struct jpeg_decomp_master *master;\n  struct jpeg_d_main_controller *main;\n  struct jpeg_d_coef_controller *coef;\n  struct jpeg_d_post_controller *post;\n  struct jpeg_input_controller *inputctl;\n  struct jpeg_marker_reader *marker;\n  struct jpeg_entropy_decoder *entropy;\n  struct jpeg_inverse_dct *idct;\n  struct jpeg_upsampler *upsample;\n  struct jpeg_color_deconverter *cconvert;\n  struct jpeg_color_quantizer *cquantize;\n}',
                definition_line=472,
                file_path="/src/libjpeg-turbo/jpeglib.h",
            ),
        ),
        (
            "j_decompress_ptr",
            "/src/libjpeg-turbo/jpeglib.h",
            False,
            TestTypeDefinitionInfo(
                name="j_decompress_ptr",
                type=TypeDefinitionType.TYPEDEF,
                definition="typedef struct jpeg_decompress_struct *j_decompress_ptr;",
                definition_line=292,
                file_path="/src/libjpeg-turbo/jpeglib.h",
            ),
        ),
    ],
)
@pytest.mark.integration
def test_libjpeg_get_type_definitions(
    libjpeg_oss_fuzz_task: ChallengeTask,
    libjpeg_oss_fuzz_cq: CodeQuery,
    type_name,
    file_path,
    fuzzy,
    type_definition_info,
):
    """Test that we can get type defs"""
    common_test_get_type_definitions(
        libjpeg_oss_fuzz_task,
        libjpeg_oss_fuzz_cq,
        type_name,
        file_path,
        fuzzy,
        type_definition_info,
    )
