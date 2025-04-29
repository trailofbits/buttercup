# Registry Cache

A simple Docker Registry configured as a pull-through cache for ghcr.io images.

## Usage

To use the registry cache in your deployments, modify your image references to use the local registry:

**Original image reference:**
```
ghcr.io/aixcc-finals/afc-crs-trail-of-bits/buttercup-orchestrator:main
```

**Using the cache:**
```
buttercup-registry-cache/aixcc-finals/afc-crs-trail-of-bits/buttercup-orchestrator:main
```

or with release name:

```
<release-name>-registry-cache/aixcc-finals/afc-crs-trail-of-bits/buttercup-orchestrator:main
```

The registry uses HTTP on port 80. 