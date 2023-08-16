# Common Corpus (common-corpus)
Common Corpus is used to build coverage-minimized corpus data sets for fuzzing.

# Usage
1. Follow the initial setup instructions at ["How to Build a Fuzzing Corpus"](https://blog.isosceles.com/how-to-build-a-corpus-for-fuzzing/) on the Isosceles blog (steps 1 through 7).
2. Compile your target binary with SanitizerCoverage enabled (e.g. with `-fsanitize=address -fsanitize-coverage=trace-pc-guard`).
3. Setup the configuration variables in the header of `common_corpus.py`. This includes information about the file format, the target command line, and the access keys that are used for reading Common Crawl data on S3.
4. Run the `common_corpus.py` script and supply the CSV file created above as the first argument.

Corpus files will be created in the `out` directory. The tool will output a "+" for each interesting file added to the corpus, and a "." for tests that did not result in new code coverage.
