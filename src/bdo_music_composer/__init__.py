"""Application-layer packages for BDO Music Composer.

Independent format and optimization libraries remain in their existing
top-level packages. Subpackage initializers intentionally avoid eager imports
so moving a focused owner cannot introduce GUI startup side effects.
"""
