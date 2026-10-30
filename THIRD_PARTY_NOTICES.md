# Third-party notices

The wheel contains new project code only. It does not vendor NumPy, SciPy, a BLAS library, a device reader, or a copied environment. Dependencies are installed separately and retain their own license files. The project's BSD-3-Clause license does not replace those terms.

|Component|Use|Core license and primary source|
|---|---|---|
|NumPy|Runtime numerical arrays|BSD-3-Clause; [official license](https://github.com/numpy/numpy/blob/main/LICENSE.txt)|
|SciPy|Runtime Student-t quantiles|BSD-3-Clause; [official license](https://github.com/scipy/scipy/blob/main/LICENSE.txt)|
|Matplotlib|Optional `paper` reports|Matplotlib license based on the PSF license; [official license](https://matplotlib.org/stable/project/license.html)|
|contourpy / cycler / kiwisolver|Optional plotting dependencies|BSD-3-Clause; retain their distributed license files|
|fonttools / pyparsing / six|Optional plotting dependencies|MIT; retain their distributed license files|
|Pillow|Optional plotting dependency|MIT-CMU; retain its distributed license file|
|python-dateutil|Optional plotting dependency|BSD-3-Clause or Apache-2.0; [official dual-license terms](https://github.com/dateutil/dateutil/blob/master/LICENSE)|
|tzdata|Optional plotting dependency|Apache-2.0 package code and separately attributed IANA timezone data; retain distributed notices|
|Hatchling / Hatch|Build only|MIT; [official license](https://github.com/pypa/hatch/blob/master/LICENSE.txt)|
|pytest|Development tests only|MIT; [official license](https://github.com/pytest-dev/pytest/blob/main/LICENSE)|
|iniconfig / pluggy|Development dependencies|MIT|
|packaging|Build/development/plotting dependency|Apache-2.0 or BSD-2-Clause|
|Pygments|Development dependency|BSD-2-Clause|

NumPy and SciPy binary distributions may contain separately licensed components such as BLAS/LAPACK and compiler runtimes. If redistributing dependency wheels, containers or native libraries, preserve and inspect the complete licenses of those exact artifacts. This candidate does not bundle them. Exact dependency versions are in `uv.lock`; release audit records installed metadata without copying third-party source.

The JavaScript viewer uses browser/Node platform APIs and vendors no third-party JavaScript, fonts or trackers. Its favicon is project-authored SVG. The four research images are project-generated, disclosure-reviewed aggregates, not participant images. Synthetic CSV/JSON fixtures come from the project's explicit generators.

The collective copyright label `SCM Research contributors` identifies this project's new contributions and is not a claim of institutional authorship. Individual authorship and contribution ownership still require confirmation before public release. No license is granted here for private research data or unknown-license device adapters.

