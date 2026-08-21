# Pull Request Template

## Description
Brief description of what this PR does.

## Type of change
- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Image build pipeline change

## Testing
Please describe how you tested this:
- [ ] Tested on Raspberry Pi 4 with RTL-SDR v4
- [ ] Tested WiFi monitoring with tshark
- [ ] Tested GPS integration with NEO-6M
- [ ] Verified web dashboard loads and displays correctly
- [ ] Verified exports (KML/CSV/GPX) work
- [ ] Ran `python3 -m pytest aperture/tests/ -v`

## Checklist
- [ ] Code follows the project's style guidelines
- [ ] I have performed a self-review of my own code
- [ ] I have commented my code, particularly in hard-to-understand areas
- [ ] I have made corresponding changes to the documentation
- [ ] My changes generate no new warnings
- [ ] I have added tests that prove my fix is effective or that my feature works
