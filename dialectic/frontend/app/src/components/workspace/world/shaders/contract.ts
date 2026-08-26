/** One post-process style stage, in God's Eye View's own shader shape.
 *
 * `intensity` is supplied by the stage manager for every style (0 = the stage
 * is off and disabled); `time` is supplied only to shaders that declare it.
 * Everything in `uniforms` is a tunable the shader author exposed.
 */
export interface WorldShaderUniform {
  default: number
  min: number
  max: number
  label: string
}

export interface WorldShader {
  name: string
  uniforms?: Record<string, WorldShaderUniform>
  fragmentShader: string
}
