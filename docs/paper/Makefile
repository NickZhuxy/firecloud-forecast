# Build the LaTeX paper.
# Targets:
#   make           — build paper.pdf (default)
#   make clean     — remove all generated artifacts
#   make watch     — rebuild on every source change (requires fswatch)

PAPER := paper

.PHONY: all clean watch

all: $(PAPER).pdf

$(PAPER).pdf: $(PAPER).tex references.bib figures/fig1_extinction_spectrum.png figures/fig2_horizon_depression.png figures/fig3_olympic_peninsula.png
	pdflatex -interaction=nonstopmode $(PAPER).tex
	bibtex $(PAPER)
	pdflatex -interaction=nonstopmode $(PAPER).tex
	pdflatex -interaction=nonstopmode $(PAPER).tex

clean:
	rm -f $(PAPER).aux $(PAPER).bbl $(PAPER).blg $(PAPER).log $(PAPER).out $(PAPER).pdf $(PAPER).toc

watch:
	@command -v fswatch >/dev/null || { echo "fswatch not installed (brew install fswatch)"; exit 1; }
	@echo "Watching for changes…"
	@while true; do \
		fswatch -1 $(PAPER).tex references.bib figures/ >/dev/null; \
		$(MAKE) all; \
	done
