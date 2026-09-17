"""
Machine-learning package
========================
Text classification of product names into warehouse categories, implemented
from scratch on the Python standard library.

Nothing here imports scikit-learn or numpy. That is a deliberate constraint, not
a limitation to apologise for: the models are small, the maths is well
understood, and writing them out means every number the dashboard reports can be
traced to a line of code in this package rather than to a library's defaults.

Layout
------
``dataset``   the labelled training data, plus whatever the user has taught the
              system through the catalogue
``features``  tokenisers and vectorisers (bag of words, TF-IDF, char n-grams)
``models``    four independent classifiers with a common interface
``metrics``   accuracy, precision, recall, F1 and confusion matrices
``evaluate``  stratified splits and k-fold cross-validation
``registry``  trains every model, compares them honestly, and picks a winner
"""
