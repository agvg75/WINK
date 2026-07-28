# NIKE 11.28

- The AFD neuronal tracker now offers **Use full frame**; drawing a crop is optional.
- ROI **Accept** captures visible selector geometry even if a backend misses the release callback.
- **Clear** removes current and committed ROI drawings; **Undo** removes the latest drawing.
- Canceling the AFD or DIC working-region editor no longer discards the loaded recording. It can reopen immediately or continue full-frame.
- The corrected shared ROI behavior is available to compatible tools using the common editor.
- Uterine morphology now requires four expected territories: anterior um1, anterior um2, posterior um1, and posterior um2.
- Uterine segmentation uses adjustable multiscale bright-ridge detection with compact-puncta rejection and a mask/skeleton/vector preview before saving.
- Outputs now include `strand_vectors.csv`, `uterine_regions.csv`, automatic segmentation QC, and an explicit `no_detectable_network` observational category.
- Tissue-specific uterine parameters are not silently applied to the pharyngeal adapter.
- The pharynx adapter now previews four connected expected territories using its own anatomy: elongated procorpus, oval metacorpus, elongated isthmus, and oval terminal bulb. The linked centerline keeps them end-to-end while remaining bendable.
