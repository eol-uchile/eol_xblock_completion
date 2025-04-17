import setuptools

setuptools.setup(
    name="xblockcompletion",
    version="0.0.3",
    author="Oficina EOL UChile",
    author_email="eol-ing@uchile.cl",
    description="EOL Xbloxk Completion",
    url="https://eol.uchile.cl",
    packages=setuptools.find_packages(),
    install_requires=["unidecode>=1.1.1"],
    classifiers=[
        "Programming Language :: Python :: 2",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    entry_points={
        "lms.djangoapp": ["xblockcompletion = xblockcompletion.apps:XblockCompletionConfig"]},
)
